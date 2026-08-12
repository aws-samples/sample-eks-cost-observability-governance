# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Cost Governance Operator - Phase 3: Cost Collection + Violation Reporting
Watches CostGovernance CRDs, scans pods for compliance, and collects cost data.
Reports violations via Events, ViolationReport CRDs, and Prometheus metrics.
"""
import logging
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


@kopf.on.create('cost-governance.io', 'v1alpha1', 'costgovernances')
def create_handler(spec, name, namespace, logger, **kwargs):
    """Handle CostGovernance resource creation."""
    logger.info(f"CostGovernance '{name}' created in namespace '{namespace}'")
    logger.info(f"Spec: {spec}")

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

    # Phase 1: Just log, no actual processing
    return {'message': 'CostGovernance resource updated successfully'}


@kopf.on.delete('cost-governance.io', 'v1alpha1', 'costgovernances')
def delete_handler(spec, name, namespace, logger, **kwargs):
    """Handle CostGovernance resource deletion."""
    logger.info(f"CostGovernance '{name}' deleted from namespace '{namespace}'")

    # Phase 1: Just log, no actual cleanup needed
    return {'message': 'CostGovernance resource deleted successfully'}


@kopf.on.timer('cost-governance.io', 'v1alpha1', 'costgovernances', interval=300.0)
def compliance_scan_handler(spec, name, namespace, logger, **kwargs):
    """Periodic compliance scan - runs every 5 minutes."""
    logger.info(f"Running compliance scan for CostGovernance '{name}'")

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
