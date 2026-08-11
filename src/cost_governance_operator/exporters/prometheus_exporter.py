"""
Prometheus Metrics Exporter

Exposes cost governance metrics in Prometheus format at /metrics endpoint.

Metrics exposed:
- cost_governance_compliance_rate - Overall compliance rate (0-100)
- cost_governance_total_pods - Total number of pods scanned
- cost_governance_compliant_pods - Number of compliant pods
- cost_governance_violating_pods - Number of pods with violations
- cost_governance_violations_by_type - Violation count by type
- cost_governance_violations_by_namespace - Violation count by namespace
- cost_governance_violations_by_label - Violation count by label
- cost_governance_total_cost - Total EKS cost in USD
- cost_governance_attribution_rate - Cost attribution rate (0-100)

Usage:
    exporter = PrometheusExporter()
    exporter.update_compliance_metrics(summary)
    exporter.update_cost_metrics(cost_summary)

    # Metrics are automatically exposed via Kopf's /metrics endpoint
"""


from prometheus_client import Counter, Gauge, Histogram, Info


class PrometheusExporter:
    """Exports cost governance metrics to Prometheus."""

    def __init__(self):
        """Initialize Prometheus metrics."""

        # Compliance metrics
        self.compliance_rate = Gauge(
            'cost_governance_compliance_rate',
            'Compliance rate percentage (0-100)',
            ['governance_name', 'governance_namespace']
        )

        self.total_pods = Gauge(
            'cost_governance_total_pods',
            'Total number of pods scanned',
            ['governance_name', 'governance_namespace']
        )

        self.compliant_pods = Gauge(
            'cost_governance_compliant_pods',
            'Number of compliant pods',
            ['governance_name', 'governance_namespace']
        )

        self.violating_pods = Gauge(
            'cost_governance_violating_pods',
            'Number of pods with violations',
            ['governance_name', 'governance_namespace']
        )

        # Violation details
        self.violations_by_type = Gauge(
            'cost_governance_violations_by_type',
            'Number of violations by type',
            ['governance_name', 'governance_namespace', 'violation_type']
        )

        self.violations_by_namespace = Gauge(
            'cost_governance_violations_by_namespace',
            'Number of violations by namespace',
            ['governance_name', 'governance_namespace', 'pod_namespace']
        )

        self.violations_by_label = Gauge(
            'cost_governance_violations_by_label',
            'Number of violations by label',
            ['governance_name', 'governance_namespace', 'label']
        )

        # Cost metrics
        self.total_cost = Gauge(
            'cost_governance_total_cost_usd',
            'Total EKS cost in USD',
            ['governance_name', 'governance_namespace', 'cluster']
        )

        self.attribution_rate = Gauge(
            'cost_governance_attribution_rate',
            'Cost attribution rate percentage (0-100)',
            ['governance_name', 'governance_namespace', 'cluster']
        )

        self.tagged_cost = Gauge(
            'cost_governance_tagged_cost_usd',
            'Cost properly attributed with tags in USD',
            ['governance_name', 'governance_namespace', 'cluster']
        )

        self.untagged_cost = Gauge(
            'cost_governance_untagged_cost_usd',
            'Cost not attributed (missing tags) in USD',
            ['governance_name', 'governance_namespace', 'cluster']
        )

        self.namespace_cost = Gauge(
            'cost_governance_namespace_cost_usd',
            'Cost by namespace in USD',
            ['governance_name', 'governance_namespace', 'cluster', 'pod_namespace']
        )

        self.team_cost = Gauge(
            'cost_governance_team_cost_usd',
            'Cost by team in USD',
            ['governance_name', 'governance_namespace', 'cluster', 'team', 'business_unit']
        )

        # Cost utilization metrics
        self.namespace_unused_cost = Gauge(
            'cost_governance_namespace_unused_cost_usd',
            'Unused (wasted) cost by namespace in USD',
            ['governance_name', 'governance_namespace', 'cluster', 'pod_namespace']
        )

        self.namespace_cost_efficiency = Gauge(
            'cost_governance_namespace_cost_efficiency_pct',
            'Cost efficiency percentage by namespace (split_cost / total_reserved_cost * 100)',
            ['governance_name', 'governance_namespace', 'cluster', 'pod_namespace']
        )

        # Scan metrics
        self.scan_duration = Histogram(
            'cost_governance_scan_duration_seconds',
            'Compliance scan duration in seconds',
            ['governance_name', 'governance_namespace']
        )

        self.scan_errors = Counter(
            'cost_governance_scan_errors_total',
            'Total number of scan errors',
            ['governance_name', 'governance_namespace', 'error_type']
        )

        # Info metric for operator version
        self.operator_info = Info(
            'cost_governance_operator',
            'Cost Governance Operator information'
        )
        self.operator_info.info({
            'version': '1.0.0',
            'phase': '3'
        })

    def update_compliance_metrics(
        self,
        summary,
        cg_name: str,
        cg_namespace: str
    ):
        """
        Update compliance metrics from scan summary.

        Args:
            summary: ComplianceSummary object
            cg_name: CostGovernance resource name
            cg_namespace: CostGovernance namespace
        """
        labels = {
            'governance_name': cg_name,
            'governance_namespace': cg_namespace
        }

        # Update basic metrics
        self.compliance_rate.labels(**labels).set(summary.compliance_rate)
        self.total_pods.labels(**labels).set(summary.total_pods)
        self.compliant_pods.labels(**labels).set(summary.compliant_pods)
        self.violating_pods.labels(**labels).set(summary.non_compliant_pods)

        # Update violation breakdown metrics
        self._update_violation_details(summary, cg_name, cg_namespace)

    def _update_violation_details(
        self,
        summary,
        cg_name: str,
        cg_namespace: str
    ):
        """
        Update detailed violation metrics.

        Args:
            summary: ComplianceSummary object
            cg_name: CostGovernance resource name
            cg_namespace: CostGovernance namespace
        """
        # Reset counters (so removed violations go to 0)
        # We need to track which labels we've seen to clean up old ones

        # Count violations by type, namespace, and label
        by_type = {}
        by_namespace = {}
        by_label = {}

        # Get non-compliant pods
        non_compliant_pods = [r for r in summary.pod_results if not r.is_compliant]

        for pod_result in non_compliant_pods:
            # Count by namespace
            ns = pod_result.namespace
            by_namespace[ns] = by_namespace.get(ns, 0) + 1

            # Parse violations to categorize
            for v_msg in pod_result.validation_result.violations:
                if 'Missing required label:' in v_msg:
                    by_type['MissingLabel'] = by_type.get('MissingLabel', 0) + 1
                    label = v_msg.split('Missing required label:')[1].strip()
                    by_label[label] = by_label.get(label, 0) + 1
                elif (
                    'missing resource requests' in v_msg.lower()
                    or 'missing CPU request' in v_msg
                    or 'missing memory request' in v_msg
                ):
                    by_type['MissingResourceRequests'] = by_type.get('MissingResourceRequests', 0) + 1
                elif 'exceeds threshold' in v_msg.lower():
                    by_type['ExceedsResourceThreshold'] = by_type.get('ExceedsResourceThreshold', 0) + 1
                elif 'Invalid' in v_msg:
                    by_type['InvalidValue'] = by_type.get('InvalidValue', 0) + 1
                    if ':' in v_msg:
                        label = v_msg.split(':')[0].replace('Invalid ', '').strip()
                        by_label[label] = by_label.get(label, 0) + 1

        # Update metrics
        for v_type, count in by_type.items():
            self.violations_by_type.labels(
                governance_name=cg_name,
                governance_namespace=cg_namespace,
                violation_type=v_type
            ).set(count)

        for ns, count in by_namespace.items():
            self.violations_by_namespace.labels(
                governance_name=cg_name,
                governance_namespace=cg_namespace,
                pod_namespace=ns
            ).set(count)

        for label, count in by_label.items():
            self.violations_by_label.labels(
                governance_name=cg_name,
                governance_namespace=cg_namespace,
                label=label
            ).set(count)

    def update_cost_metrics(
        self,
        cost_summary,
        cg_name: str,
        cg_namespace: str,
        cluster_name: str
    ):
        """
        Update cost metrics from cost collection summary.

        Args:
            cost_summary: CostCollectionSummary object
            cg_name: CostGovernance resource name
            cg_namespace: CostGovernance namespace
            cluster_name: EKS cluster name
        """
        base_labels = {
            'governance_name': cg_name,
            'governance_namespace': cg_namespace,
            'cluster': cluster_name
        }

        # Update overall cost metrics
        self.total_cost.labels(**base_labels).set(float(cost_summary.total_cost))
        self.attribution_rate.labels(**base_labels).set(
            cost_summary.attribution.attribution_rate
        )
        self.tagged_cost.labels(**base_labels).set(
            float(cost_summary.attribution.tagged_cost)
        )
        self.untagged_cost.labels(**base_labels).set(
            float(cost_summary.attribution.untagged_cost)
        )

        # Update namespace costs
        for ns_cost in cost_summary.by_namespace:
            self.namespace_cost.labels(
                governance_name=cg_name,
                governance_namespace=cg_namespace,
                cluster=cluster_name,
                pod_namespace=ns_cost.namespace
            ).set(float(ns_cost.total_cost))

        # Update team costs (if available)
        for team_cost in cost_summary.by_team:
            self.team_cost.labels(
                governance_name=cg_name,
                governance_namespace=cg_namespace,
                cluster=cluster_name,
                team=team_cost.team_name,
                business_unit=team_cost.business_unit or 'unknown'
            ).set(float(team_cost.total_cost))

        # Update cost utilization metrics (if available)
        for cu in cost_summary.cost_utilization:
            ns_labels = {
                'governance_name': cg_name,
                'governance_namespace': cg_namespace,
                'cluster': cluster_name,
                'pod_namespace': cu.namespace
            }
            self.namespace_unused_cost.labels(**ns_labels).set(float(cu.unused_cost))
            self.namespace_cost_efficiency.labels(**ns_labels).set(cu.cost_efficiency_pct)

    def record_scan_duration(
        self,
        duration_seconds: float,
        cg_name: str,
        cg_namespace: str
    ):
        """
        Record compliance scan duration.

        Args:
            duration_seconds: Scan duration in seconds
            cg_name: CostGovernance resource name
            cg_namespace: CostGovernance namespace
        """
        self.scan_duration.labels(
            governance_name=cg_name,
            governance_namespace=cg_namespace
        ).observe(duration_seconds)

    def record_scan_error(
        self,
        error_type: str,
        cg_name: str,
        cg_namespace: str
    ):
        """
        Record a scan error.

        Args:
            error_type: Type of error (e.g., 'registry_load_failed', 'k8s_api_error')
            cg_name: CostGovernance resource name
            cg_namespace: CostGovernance namespace
        """
        self.scan_errors.labels(
            governance_name=cg_name,
            governance_namespace=cg_namespace,
            error_type=error_type
        ).inc()
