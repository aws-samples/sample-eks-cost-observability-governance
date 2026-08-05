"""
Violation Reporter - Creates ViolationReport CRs and Kubernetes Events

This module handles reporting compliance violations through multiple channels:
1. ViolationReport CRD - Persistent, queryable violation records
2. Kubernetes Events - Immediate visibility in pod descriptions
3. Prometheus Metrics - Time-series data for monitoring

Usage:
    reporter = ViolationReporter(k8s_client, logger)
    reporter.report_violations(summary, cg_name, cg_namespace)
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from kubernetes import client
import logging


class ViolationReporter:
    """Reports compliance violations through multiple channels."""

    def __init__(self, k8s_client, logger: logging.Logger):
        """
        Initialize violation reporter.

        Args:
            k8s_client: Kubernetes API client
            logger: Logger instance
        """
        self.k8s_client = k8s_client
        self.logger = logger
        self.core_v1 = client.CoreV1Api(k8s_client)
        self.custom_api = client.CustomObjectsApi(k8s_client)

    def report_violations(
        self,
        summary,
        cg_name: str,
        cg_namespace: str
    ) -> Optional[str]:
        """
        Report violations through all channels.

        Args:
            summary: ComplianceSummary object with violation details
            cg_name: CostGovernance resource name
            cg_namespace: CostGovernance resource namespace

        Returns:
            ViolationReport resource name if created, None otherwise
        """
        try:
            # 1. Create ViolationReport CRD
            report_name = self._create_violation_report(summary, cg_name, cg_namespace)

            # 2. Create Kubernetes Events for each violation
            non_compliant_pods = [r for r in summary.pod_results if not r.is_compliant]
            self._create_violation_events(non_compliant_pods)

            # 3. Update metrics (metrics are read from summary by exporter)
            self.logger.info(
                f"Reported {summary.non_compliant_pods} violations via "
                f"ViolationReport ({report_name}), Events, and Metrics"
            )

            return report_name

        except Exception as e:
            self.logger.error(f"Failed to report violations: {e}", exc_info=True)
            return None

    def _create_violation_report(
        self,
        summary,
        cg_name: str,
        cg_namespace: str
    ) -> str:
        """
        Create ViolationReport custom resource.

        Args:
            summary: ComplianceSummary object
            cg_name: CostGovernance resource name
            cg_namespace: CostGovernance namespace

        Returns:
            Name of created ViolationReport
        """
        timestamp = datetime.now(timezone.utc)
        report_name = f"{cg_name}-{timestamp.strftime('%Y%m%d-%H%M%S')}"

        # Get non-compliant pods from pod_results
        non_compliant_pods = [r for r in summary.pod_results if not r.is_compliant]

        # Build violation summary statistics
        violation_summary = self._build_violation_summary(non_compliant_pods)

        # Build violations list
        violations_list = []
        for pod_result in non_compliant_pods:
            pod_violations = []
            for v_msg in pod_result.validation_result.violations:
                # Parse violation message to determine type
                v_type, v_details = self._parse_violation_message(v_msg)
                pod_violations.append(v_details)

            violations_list.append({
                'pod': pod_result.name,
                'namespace': pod_result.namespace,
                'labels': pod_result.labels or {},
                'violations': pod_violations
            })

        # Create ViolationReport resource
        report = {
            'apiVersion': 'cost-governance.io/v1alpha1',
            'kind': 'ViolationReport',
            'metadata': {
                'name': report_name,
                'namespace': cg_namespace,
                'labels': {
                    'cost-governance.io/managed-by': 'cost-governance-operator',
                    'cost-governance.io/governance': cg_name
                },
                'annotations': {
                    'cost-governance.io/scan-time': timestamp.isoformat()
                }
            },
            'spec': {
                'scanTime': timestamp.isoformat(),
                'costGovernanceRef': cg_name,
                'totalPods': summary.total_pods,
                'compliantPods': summary.compliant_pods,
                'violatingPods': summary.non_compliant_pods,
                'complianceRate': summary.compliance_rate,
                'violations': violations_list,
                'violationSummary': violation_summary
            },
            'status': {
                'phase': 'Active',
                'createdAt': timestamp.isoformat()
            }
        }

        # Create the resource
        self.custom_api.create_namespaced_custom_object(
            group='cost-governance.io',
            version='v1alpha1',
            namespace=cg_namespace,
            plural='violationreports',
            body=report
        )

        self.logger.info(f"Created ViolationReport: {cg_namespace}/{report_name}")
        return report_name

    def _build_violation_summary(self, pod_results: List) -> Dict:
        """
        Build summary statistics from non-compliant pod results.

        Args:
            pod_results: List of PodScanResult objects (non-compliant only)

        Returns:
            Dictionary with violation counts by type, namespace, and label
        """
        by_type = {}
        by_namespace = {}
        by_label = {}

        for pod_result in pod_results:
            # Count by namespace
            ns = pod_result.namespace
            by_namespace[ns] = by_namespace.get(ns, 0) + 1

            # Count by violation type and label
            for v_msg in pod_result.validation_result.violations:
                if 'Missing required label:' in v_msg:
                    by_type['MissingLabel'] = by_type.get('MissingLabel', 0) + 1
                    # Extract label name
                    label = v_msg.split('Missing required label:')[1].strip()
                    by_label[label] = by_label.get(label, 0) + 1
                elif 'Invalid' in v_msg:
                    by_type['InvalidValue'] = by_type.get('InvalidValue', 0) + 1
                    # Extract label name (e.g., "Invalid cost-center:")
                    if ':' in v_msg:
                        label = v_msg.split(':')[0].replace('Invalid ', '').strip()
                        by_label[label] = by_label.get(label, 0) + 1

        return {
            'byType': by_type,
            'byNamespace': by_namespace,
            'byLabel': by_label
        }

    def _parse_violation_message(self, message: str) -> tuple:
        """
        Parse violation message into structured format.

        Args:
            message: Violation message string

        Returns:
            Tuple of (violation_type, violation_details_dict)
        """
        if 'Missing required label:' in message:
            label = message.split('Missing required label:')[1].strip()
            return 'MissingLabel', {
                'type': 'MissingLabel',
                'label': label,
                'message': message
            }
        elif 'Invalid' in message:
            # Parse invalid value violations
            # Format: "Invalid cost-center: 'CC-9999' for business-unit: 'engineering'. Valid values: CC-1234, CC-1235"
            parts = message.split(':')
            if len(parts) >= 2:
                label = parts[0].replace('Invalid ', '').strip()

                # Extract current value
                value = None
                if "'" in message:
                    value = message.split("'")[1]

                # Extract valid values
                valid_values = []
                if 'Valid values:' in message:
                    valid_str = message.split('Valid values:')[1].strip()
                    valid_values = [v.strip() for v in valid_str.split(',')]

                return 'InvalidValue', {
                    'type': 'InvalidValue',
                    'label': label,
                    'value': value,
                    'validValues': valid_values,
                    'message': message
                }
        elif 'missing resource requests' in message.lower() or 'missing CPU request' in message or 'missing memory request' in message:
            return 'MissingResourceRequests', {
                'type': 'MissingResourceRequests',
                'message': message
            }
        elif 'exceeds threshold' in message.lower():
            return 'ExceedsResourceThreshold', {
                'type': 'ExceedsResourceThreshold',
                'message': message
            }

        # Fallback for unparseable violations
        return 'MissingLabel', {
            'type': 'MissingLabel',
            'message': message
        }

    def _create_violation_events(self, pod_results: List):
        """
        Create Kubernetes Events for each pod violation.

        Args:
            pod_results: List of PodScanResult objects (non-compliant only)
        """
        for pod_result in pod_results:
            try:
                self._create_pod_violation_event(pod_result)
            except Exception as e:
                self.logger.warning(
                    f"Failed to create event for {pod_result.namespace}/{pod_result.name}: {e}"
                )

    def _create_pod_violation_event(self, pod_result):
        """
        Create a Kubernetes Event for a single pod violation.

        Uses the CoreV1 events API with a plain dict body to avoid
        compatibility issues across kubernetes client versions.

        Args:
            pod_result: PodScanResult object
        """
        # Create event name (max 253 chars)
        event_name = f"{pod_result.name}-compliance-violation"
        if len(event_name) > 253:
            event_name = event_name[:253]

        # Build event message
        violations = pod_result.validation_result.violations
        violation_count = len(violations)
        message = f"Compliance violations detected ({violation_count}):\n"
        for v in violations[:5]:  # Limit to first 5 for readability
            message += f"  - {v}\n"
        if violation_count > 5:
            message += f"  ... and {violation_count - 5} more"

        # Create event timestamp
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        # Build event as a plain dict — avoids V1Event compatibility issues
        # across kubernetes client versions
        event = {
            'apiVersion': 'v1',
            'kind': 'Event',
            'metadata': {
                'name': event_name,
                'namespace': pod_result.namespace
            },
            'involvedObject': {
                'apiVersion': 'v1',
                'kind': 'Pod',
                'name': pod_result.name,
                'namespace': pod_result.namespace
            },
            'reason': 'ComplianceViolation',
            'message': message,
            'type': 'Warning',
            'source': {
                'component': 'cost-governance-operator'
            },
            'firstTimestamp': now,
            'lastTimestamp': now,
            'count': 1
        }

        try:
            # Try to create the event
            self.core_v1.create_namespaced_event(
                namespace=pod_result.namespace,
                body=event
            )
            self.logger.debug(
                f"Created event for {pod_result.namespace}/{pod_result.name}"
            )
        except client.exceptions.ApiException as e:
            if e.status == 409:  # Conflict - event already exists
                self.logger.debug(
                    f"Event already exists for {pod_result.namespace}/{pod_result.name}"
                )
            else:
                raise

    def cleanup_old_reports(
        self,
        cg_name: str,
        cg_namespace: str,
        retention_count: int = 7
    ):
        """
        Delete old ViolationReports, keeping only the most recent N.

        Args:
            cg_name: CostGovernance resource name
            cg_namespace: CostGovernance namespace
            retention_count: Number of reports to retain (default: 7)
        """
        try:
            # List all ViolationReports for this CostGovernance
            reports = self.custom_api.list_namespaced_custom_object(
                group='cost-governance.io',
                version='v1alpha1',
                namespace=cg_namespace,
                plural='violationreports',
                label_selector=f'cost-governance.io/governance={cg_name}'
            )

            items = reports.get('items', [])
            if len(items) <= retention_count:
                return  # Nothing to clean up

            # Sort by creation timestamp (oldest first)
            items.sort(key=lambda x: x['metadata']['creationTimestamp'])

            # Delete oldest reports
            to_delete = items[:len(items) - retention_count]
            for report in to_delete:
                report_name = report['metadata']['name']
                self.custom_api.delete_namespaced_custom_object(
                    group='cost-governance.io',
                    version='v1alpha1',
                    namespace=cg_namespace,
                    plural='violationreports',
                    name=report_name
                )
                self.logger.info(f"Deleted old ViolationReport: {report_name}")

        except Exception as e:
            self.logger.warning(f"Failed to cleanup old reports: {e}")
