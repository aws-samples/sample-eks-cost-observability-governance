# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Cost Governance Operator - Phase 3: Cost Collection + Violation Reporting
Watches CostGovernance CRDs, scans pods for compliance, and collects cost data.
Reports violations via Events, ViolationReport CRDs, and Prometheus metrics.
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import kopf
from collectors.athena_collector import AthenaCollector
from config import Config
from exporters.prometheus_exporter import PrometheusExporter
from kubernetes import client
from kubernetes import config as k8s_config
from prometheus_client import start_http_server
from reporters.violation_reporter import ViolationReporter
from utils.registry import load_registry_from_k8s
from validators.validators import Validator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default required labels when a CostGovernance spec omits them.
DEFAULT_REQUIRED_LABELS = [
    'cost-center', 'business-unit', 'team', 'application', 'environment'
]

# In-memory cache of the active governance policy, populated by the CostGovernance
# create/update handlers. The admission webhook reads this on the pod-creation hot
# path so it never has to make an API call per request. Keyed by "namespace/name".
_active_policies: dict[str, dict] = {}


def _cache_policy(name: str, namespace: str, spec: dict) -> None:
    """Store the enforcement-relevant fields of a CostGovernance spec in the cache."""
    _active_policies[f'{namespace}/{name}'] = {
        'enforcementMode': spec.get('enforcementMode', 'audit'),
        'requiredLabels': spec.get('requiredLabels') or DEFAULT_REQUIRED_LABELS,
    }


def _get_active_policy() -> dict | None:
    """Return the most permissive-to-evaluate active policy, or None if none cached.

    For this PoC a single CostGovernance policy governs the cluster, so we return
    any cached policy. If several exist, prefer one in 'enforce' mode so enforcement
    is not silently skipped.
    """
    if not _active_policies:
        return None
    for policy in _active_policies.values():
        if policy.get('enforcementMode') == 'enforce':
            return policy
    return next(iter(_active_policies.values()))


class ServiceWebhookServer(kopf.WebhookServer):
    """Webhook server for in-cluster (EKS) operation.

    Serves the admission HTTPS endpoint on 0.0.0.0:<port> using a pre-generated
    certificate mounted from a Secret. The webhook is registered via a STATIC
    ValidatingWebhookConfiguration (not managed by Kopf), whose caBundle matches
    this cert's CA. Because the CA is fixed and the config is owned outside the
    operator, neither rotates or gets wiped on restart -- avoiding the churn of
    Kopf-managed webhook configurations on EKS.
    """

    def __init__(self, port: int, certfile: str, pkeyfile: str):
        super().__init__(
            # Bind all interfaces: the webhook runs in a pod and the API server
            # reaches it via the Service, so binding to loopback would make it
            # unreachable. TLS + a namespaced Service scope the exposure.
            addr='0.0.0.0',  # nosec B104 - must be reachable via the Service
            port=port,
            # Serve with the pre-generated cert mounted from a Secret. The CA is
            # fixed and matches the caBundle in the static webhook config, so it
            # never rotates on restart.
            certfile=certfile,
            pkeyfile=pkeyfile,
        )


# Initialize Prometheus exporter (global singleton)
prometheus_exporter = PrometheusExporter()

# Start Prometheus metrics HTTP server
try:
    start_http_server(8000)
    logger.info("Prometheus metrics server started on port 8000 at /metrics")
except Exception as e:
    logger.error(f"Failed to start Prometheus metrics server: {e}")


@kopf.on.startup()
def startup_handler(settings: kopf.OperatorSettings, **_):
    """Configure operator on startup."""
    settings.persistence.finalizer = 'cost-governance.io/finalizer'
    settings.persistence.progress_storage = kopf.AnnotationsProgressStorage()
    settings.persistence.diffbase_storage = kopf.AnnotationsDiffBaseStorage()

    # Admission webhook (enforce mode). The operator only SERVES the webhook on
    # an HTTPS port using a cert mounted from a Secret. It does NOT manage the
    # ValidatingWebhookConfiguration -- that is a static manifest we apply once
    # (see k8s_configs/webhook/). This avoids the fragility of Kopf-managed
    # webhook configs on EKS (empty/rotated/wiped configs across restarts).
    #
    # Fail-open safety comes from the static config's failurePolicy: Ignore.
    #
    # If the cert files are not mounted yet (e.g. the webhook Secret has not been
    # created), skip serving the webhook rather than crash-looping. Enforcement
    # is simply inactive until the cert is present; the static config's
    # failurePolicy: Ignore means pods are still admitted in the meantime.
    if Config.WEBHOOK_ENABLED:
        cert_present = (
            os.path.exists(Config.WEBHOOK_CERT_FILE)
            and os.path.exists(Config.WEBHOOK_KEY_FILE)
        )
        if cert_present:
            settings.admission.managed = None  # we own the config, Kopf must not manage it
            settings.admission.server = ServiceWebhookServer(
                port=Config.WEBHOOK_PORT,
                certfile=Config.WEBHOOK_CERT_FILE,
                pkeyfile=Config.WEBHOOK_KEY_FILE,
            )
            logger.info(
                f"Admission webhook serving on :{Config.WEBHOOK_PORT} "
                f"(static config, fail-open)"
            )
        else:
            logger.warning(
                f"Webhook cert not found at {Config.WEBHOOK_CERT_FILE}; "
                f"enforce mode is INACTIVE until the cert Secret is mounted. "
                f"Run 'make deploy-webhook'."
            )

    logger.info("=" * 60)
    logger.info("Cost Governance Operator - Phase 3: Cost Collection")
    logger.info("=" * 60)
    logger.info("Operator starting...")
    logger.info("Watching for CostGovernance resources")
    logger.info(f"Configuration: {Config.display()}")
    logger.info("=" * 60)


def get_k8s_client():
    """Get Kubernetes API client."""
    try:
        # Try in-cluster config first (when running in pod)
        k8s_config.load_incluster_config()
        logger.info("Using in-cluster Kubernetes config")
    except k8s_config.ConfigException:
        # Fall back to kubeconfig (for local development)
        k8s_config.load_kube_config()
        logger.info("Using kubeconfig")

    return client.ApiClient()


@kopf.on.resume('cost-governance.io', 'v1alpha1', 'costgovernances')
def resume_handler(spec, name, namespace, logger, **kwargs):
    """Re-adopt existing CostGovernance resources on operator (re)start.

    Kopf fires on.resume (not on.create) for objects that already existed before
    the operator started. Without this, the in-memory policy cache would be empty
    after a restart and the admission webhook would have nothing to enforce.
    """
    _cache_policy(name, namespace, spec)
    logger.info(
        f"Resumed CostGovernance '{name}' — enforcement mode: "
        f"{spec.get('enforcementMode', 'audit')}"
    )
    return {'message': 'CostGovernance resource resumed'}


@kopf.on.create('cost-governance.io', 'v1alpha1', 'costgovernances')
def create_handler(spec, name, namespace, logger, **kwargs):
    """Handle CostGovernance resource creation."""
    logger.info(f"CostGovernance '{name}' created in namespace '{namespace}'")
    logger.info(f"Spec: {spec}")

    # Cache policy so the admission webhook can enforce it without an API call.
    _cache_policy(name, namespace, spec)
    logger.info(f"Enforcement mode: {spec.get('enforcementMode', 'audit')}")

    # Trigger initial compliance scan
    try:
        perform_compliance_scan(spec, name, namespace, logger)
    except Exception as e:
        logger.error(f"Initial compliance scan failed: {e}")

    return {'message': 'CostGovernance resource created successfully'}


@kopf.on.update('cost-governance.io', 'v1alpha1', 'costgovernances')
def update_handler(spec, name, namespace, old, new, logger, **kwargs):
    """Handle CostGovernance resource updates."""
    logger.info(f"CostGovernance '{name}' updated in namespace '{namespace}'")
    logger.info(f"Old spec: {old.get('spec', {})}")
    logger.info(f"New spec: {new.get('spec', {})}")

    # Refresh the cached policy so enforcement picks up mode/label changes.
    _cache_policy(name, namespace, spec)
    logger.info(f"Enforcement mode: {spec.get('enforcementMode', 'audit')}")

    return {'message': 'CostGovernance resource updated successfully'}


@kopf.on.delete('cost-governance.io', 'v1alpha1', 'costgovernances')
def delete_handler(spec, name, namespace, logger, **kwargs):
    """Handle CostGovernance resource deletion."""
    logger.info(f"CostGovernance '{name}' deleted from namespace '{namespace}'")

    # Drop the cached policy so the webhook stops enforcing it.
    _active_policies.pop(f'{namespace}/{name}', None)

    return {'message': 'CostGovernance resource deleted successfully'}


# Namespaces the admission webhook never blocks, so system/operator workloads
# can always start even in enforce mode.
WEBHOOK_EXEMPT_NAMESPACES = {
    'kube-system',
    'kube-public',
    'kube-node-lease',
    'cost-governance-system',
}


# NOTE: id must be hyphenated (no underscores). Kopf uses the handler id as the
# webhook's URL/path segment, and Kubernetes validates that segment as an
# RFC 1123 subdomain, which forbids underscores.
#
# Do NOT set ignore_failures=True here: in Kopf that also suppresses handler
# rejections (AdmissionError), so enforce mode could never deny. Fail-open
# safety instead comes from the webhook config's failurePolicy: Ignore, which
# Kopf sets -- that protects against the operator being unreachable without
# disabling intentional denials.
@kopf.on.validate('', 'v1', 'pods', operation='CREATE', id='enforce-pod-labels')
def enforce_pod_labels(meta, namespace, labels, warnings, logger, **_):
    """Admission webhook: check pods for required cost-attribution labels.

    - enforce mode: reject pods missing required labels (raises AdmissionError).
    - audit mode (or no policy): attach a warning but allow the pod.

    System and operator namespaces are always exempt.
    """
    pod_labels = labels or {}
    logger.info(
        f"[webhook] admission review: namespace={namespace!r} "
        f"label_keys={sorted(pod_labels.keys())} "
        f"policies_cached={len(_active_policies)}"
    )

    if namespace in WEBHOOK_EXEMPT_NAMESPACES:
        logger.info(f"[webhook] namespace {namespace} is exempt; allowing")
        return

    policy = _get_active_policy()
    if not policy:
        logger.warning("[webhook] no active CostGovernance policy cached; allowing")
        return

    required_labels = policy['requiredLabels']

    # Reuse the same label-completeness check the periodic scanner uses.
    violations = Validator.validate_label_completeness_static(pod_labels, required_labels)
    logger.info(
        f"[webhook] mode={policy['enforcementMode']} required={required_labels} "
        f"violations={violations}"
    )
    if not violations:
        return

    pod_name = meta.get('name') or meta.get('generateName', '<unnamed>')
    detail = '; '.join(violations)

    if policy['enforcementMode'] == 'enforce':
        logger.warning(f"DENY pod {namespace}/{pod_name}: {detail}")
        raise kopf.AdmissionError(
            f"Pod rejected by cost governance: {detail}. "
            f"Required labels: {', '.join(required_labels)}."
        )

    # audit mode: surface the issue without blocking.
    logger.info(f"AUDIT pod {namespace}/{pod_name}: {detail}")
    warnings.append(f"cost-governance: {detail}")


@kopf.on.timer('cost-governance.io', 'v1alpha1', 'costgovernances', interval=300.0)
def compliance_scan_handler(spec, name, namespace, logger, **kwargs):
    """Periodic compliance scan - runs every 5 minutes."""
    logger.info(f"Running compliance scan for CostGovernance '{name}'")

    # Keep the webhook's policy cache fresh (self-heals if resume didn't run).
    _cache_policy(name, namespace, spec)

    try:
        perform_compliance_scan(spec, name, namespace, logger)
    except Exception as e:
        logger.error(f"Compliance scan failed: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}

    return {'status': 'success', 'timestamp': datetime.now(timezone.utc).isoformat()}


def _load_registry(spec, k8s_client, cg_name, cg_namespace, logger):
    """
    Load registry from ConfigMap if configured.

    Args:
        spec: CostGovernance spec
        k8s_client: Kubernetes API client
        cg_name: CostGovernance resource name
        cg_namespace: CostGovernance resource namespace
        logger: Logger instance

    Returns:
        Registry instance or None
    """
    registry_config = spec.get('registryConfigMap')
    if not registry_config:
        return None

    registry_name = registry_config.get('name')
    registry_namespace = registry_config.get('namespace', cg_namespace)

    logger.info(f"Loading registry from ConfigMap: {registry_namespace}/{registry_name}")
    registry = load_registry_from_k8s(k8s_client, registry_name, registry_namespace)

    if registry:
        logger.info("Registry loaded successfully")
        if registry.infrastructure_namespaces:
            from utils.cluster_infrastructure_config import set_namespace_categories
            set_namespace_categories(registry.infrastructure_namespaces)
            logger.info(
                f"Infrastructure namespaces set from registry: "
                f"{list(registry.infrastructure_namespaces.keys())}"
            )
    else:
        logger.warning("Failed to load registry - proceeding with label completeness check only")
        prometheus_exporter.record_scan_error('registry_load_failed', cg_name, cg_namespace)

    return registry


def perform_compliance_scan(spec, cg_name, cg_namespace, logger):
    """
    Perform compliance scan and update CRD status.

    Args:
        spec: CostGovernance spec
        cg_name: CostGovernance resource name
        cg_namespace: CostGovernance resource namespace
        logger: Logger instance
    """
    logger.info("Starting compliance scan...")
    start_time = time.time()

    # Get Kubernetes client
    k8s_client = get_k8s_client()

    # Extract configuration from spec
    required_labels = spec.get('requiredLabels', [
        'cost-center', 'business-unit', 'team', 'application', 'environment'
    ])

    # Load registry if configured
    registry = _load_registry(spec, k8s_client, cg_name, cg_namespace, logger)

    # Create unified validator and run all checks
    validator = Validator(
        required_labels=required_labels,
        registry=registry,
        resource_thresholds=spec.get('resourceThresholds')
    )
    logger.info("Scanning pods across all namespaces...")
    summary = validator.validate_all()

    # Record scan duration
    scan_duration = time.time() - start_time
    prometheus_exporter.record_scan_duration(scan_duration, cg_name, cg_namespace)

    logger.info(f"Scan complete: {summary}")
    logger.info(f"  Total Pods: {summary.total_pods}")
    logger.info(f"  Compliant: {summary.compliant_pods}")
    logger.info(f"  Non-Compliant: {summary.non_compliant_pods}")
    logger.info(f"  Compliance Rate: {summary.compliance_rate:.2f}%")
    logger.info(f"  Scan Duration: {scan_duration:.2f}s")

    # Report violations via multiple channels
    if summary.non_compliant_pods > 0:
        reporter = ViolationReporter(k8s_client, logger)
        report_name = reporter.report_violations(summary, cg_name, cg_namespace)
        logger.info(f"Created ViolationReport: {report_name}")

        # Clean up old reports (keep last 7)
        reporter.cleanup_old_reports(cg_name, cg_namespace, retention_count=7)

    # Update Prometheus metrics
    prometheus_exporter.update_compliance_metrics(summary, cg_name, cg_namespace)

    # Update CRD status
    update_crd_status(k8s_client, cg_name, cg_namespace, summary, logger)


def update_crd_status(k8s_client, cg_name, cg_namespace, summary, logger):
    """
    Update CostGovernance CRD status with scan results.

    Args:
        k8s_client: Kubernetes API client
        cg_name: CostGovernance resource name
        cg_namespace: CostGovernance resource namespace
        summary: ComplianceSummary object
        logger: Logger instance
    """
    try:
        # Get custom objects API
        custom_api = client.CustomObjectsApi(k8s_client)

        # Prepare status update
        status = {
            'lastCollectionTime': datetime.now(timezone.utc).isoformat(),
            'complianceRate': summary.compliance_rate,
            'totalPods': summary.total_pods,
            'violatingPods': summary.non_compliant_pods,
            'conditions': [
                {
                    'type': 'ComplianceScanComplete',
                    'status': 'True',
                    'lastTransitionTime': datetime.now(timezone.utc).isoformat(),
                    'reason': 'ScanCompleted',
                    'message': f'Scanned {summary.total_pods} pods, {summary.compliance_rate:.2f}% compliant'
                }
            ]
        }

        # Update status subresource
        custom_api.patch_namespaced_custom_object_status(
            group='cost-governance.io',
            version='v1alpha1',
            namespace=cg_namespace,
            plural='costgovernances',
            name=cg_name,
            body={'status': status}
        )

        logger.info(f"Updated CRD status for {cg_namespace}/{cg_name}")

    except Exception as e:
        logger.error(f"Failed to update CRD status: {e}", exc_info=True)


@kopf.on.timer('cost-governance.io', 'v1alpha1', 'costgovernances', interval=3600.0, initial_delay=60.0)
def cost_collection_handler(spec, name, namespace, logger, **kwargs):
    """
    Periodic cost collection handler - runs every hour.

    Queries Athena for EKS cost data and updates CRD status.
    """
    logger.info(f"Running cost collection for CostGovernance '{name}'")

    # Check if cost collection is enabled
    cost_config = spec.get('costCollection', {})
    if not cost_config.get('enabled', True):
        logger.info("Cost collection disabled in spec")
        return {'status': 'skipped', 'reason': 'disabled'}

    try:
        # Get configuration from spec or use defaults
        database = cost_config.get('athenaDatabase', Config.ATHENA_DATABASE)
        table = cost_config.get('athenaTable', Config.ATHENA_TABLE)
        cluster_name = cost_config.get('clusterName', Config.EKS_CLUSTER_NAME)
        lookback_days = cost_config.get('lookbackDays', Config.COST_LOOKBACK_DAYS)

        # Calculate date range
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=lookback_days)

        logger.info(f"Collecting costs for cluster '{cluster_name}' from {start_date} to {end_date}")

        # Create Athena collector
        collector = AthenaCollector(
            database=database,
            table=table,
            cluster_name=cluster_name,
            s3_output=Config.ATHENA_S3_OUTPUT,
            aws_profile=Config.AWS_PROFILE,
            region=Config.AWS_REGION
        )

        # Collect cost summary
        cost_summary = collector.collect_cost_summary(start_date, end_date)

        if not cost_summary:
            logger.warning("Cost collection returned no data")
            return {'status': 'no_data'}

        # Update Prometheus metrics with cost data
        prometheus_exporter.update_cost_metrics(cost_summary, name, namespace, cluster_name)

        # Update CRD status with cost data
        update_cost_status(name, namespace, cost_summary, logger)

        logger.info(f"Cost collection complete: ${float(cost_summary.total_cost):.2f} total")
        return {
            'status': 'success',
            'total_cost': float(cost_summary.total_cost),
            'pod_count': cost_summary.pod_count,
            'attribution_rate': cost_summary.attribution.attribution_rate
        }

    except Exception as e:
        logger.error(f"Cost collection failed: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}


def update_cost_status(cg_name, cg_namespace, cost_summary, logger):
    """
    Update CostGovernance CRD status with cost data.

    Args:
        cg_name: CostGovernance resource name
        cg_namespace: CostGovernance resource namespace
        cost_summary: CostCollectionSummary object
        logger: Logger instance
    """
    try:
        # Get Kubernetes client
        k8s_client = get_k8s_client()
        custom_api = client.CustomObjectsApi(k8s_client)

        # Get current status to merge with cost data
        try:
            current = custom_api.get_namespaced_custom_object(
                group='cost-governance.io',
                version='v1alpha1',
                namespace=cg_namespace,
                plural='costgovernances',
                name=cg_name
            )
            existing_status = current.get('status', {})
        except Exception:
            existing_status = {}

        # Merge compliance data (Phase 2) with cost data (Phase 3)
        status = {
            **existing_status,  # Keep existing Phase 2 data
            'costData': cost_summary.to_dict()  # Add Phase 3 data
        }

        # Update status subresource
        custom_api.patch_namespaced_custom_object_status(
            group='cost-governance.io',
            version='v1alpha1',
            namespace=cg_namespace,
            plural='costgovernances',
            name=cg_name,
            body={'status': status}
        )

        logger.info(f"Updated cost data in CRD status for {cg_namespace}/{cg_name}")

    except Exception as e:
        logger.error(f"Failed to update cost status: {e}", exc_info=True)


@kopf.on.probe(id='liveness')
def liveness_handler(**kwargs):
    """Liveness probe for Kubernetes."""
    return {'alive': True}


@kopf.on.probe(id='readiness')
def readiness_handler(**kwargs):
    """Readiness probe for Kubernetes."""
    return {'ready': True}
