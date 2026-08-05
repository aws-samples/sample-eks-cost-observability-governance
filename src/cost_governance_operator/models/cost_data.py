"""
Data models for EKS cost collection.

These models represent cost data from AWS Cost and Usage Reports (CUR 2.0)
queried via Athena, with and without cost governance labels.
"""

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional


@dataclass
class CostRecord:
    """
    Single cost record from CUR data.

    Represents one line item from the cost report, typically corresponding
    to pod usage for a specific time period.
    """
    resource_id: str                    # Full EKS pod ARN
    namespace: str                      # Extracted from ARN
    pod_name: str                       # Extracted from ARN
    cost: Decimal                       # split_line_item_split_cost
    usage_date: date                    # When the cost was incurred

    # Cost governance labels (may be None if not tagged)
    cost_center: Optional[str] = None
    business_unit: Optional[str] = None
    team: Optional[str] = None
    application: Optional[str] = None
    environment: Optional[str] = None

    @property
    def is_tagged(self) -> bool:
        """Check if this pod has cost governance labels."""
        return self.team is not None and self.cost_center is not None

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert Decimal to float for JSON
        data['cost'] = float(self.cost)
        # Convert date to string
        data['usage_date'] = self.usage_date.isoformat()
        return data


@dataclass
class NamespaceCostSummary:
    """
    Aggregated costs for a Kubernetes namespace.

    Useful for showing cost by namespace regardless of tagging.
    """
    namespace: str
    total_cost: Decimal
    pod_count: int
    tagged_pods: int                    # Pods with cost governance labels
    untagged_pods: int                  # Pods without labels
    avg_cost_per_pod: Decimal = field(init=False)

    def __post_init__(self):
        """Calculate derived fields."""
        self.avg_cost_per_pod = (
            self.total_cost / self.pod_count if self.pod_count > 0 else Decimal('0')
        )

    @property
    def tagging_rate(self) -> float:
        """Percentage of pods with proper tags (0-100)."""
        if self.pod_count == 0:
            return 0.0
        return (self.tagged_pods / self.pod_count) * 100

    def to_dict(self) -> Dict:
        """Convert to dictionary for CRD status."""
        return {
            'namespace': self.namespace,
            'totalCost': f'${float(self.total_cost):.2f}',
            'podCount': self.pod_count,
            'taggedPods': self.tagged_pods,
            'untaggedPods': self.untagged_pods,
            'avgCostPerPod': f'${float(self.avg_cost_per_pod):.2f}',
            'taggingRate': round(self.tagging_rate, 1)
        }


@dataclass
class TeamCostSummary:
    """
    Aggregated costs for a team (requires cost governance labels).

    Only populated for pods that have proper team labels.
    """
    team_name: str
    business_unit: Optional[str]
    total_cost: Decimal
    pod_count: int
    namespaces: List[str]
    avg_cost_per_pod: Decimal = field(init=False)

    def __post_init__(self):
        """Calculate derived fields."""
        self.avg_cost_per_pod = (
            self.total_cost / self.pod_count if self.pod_count > 0 else Decimal('0')
        )

    def to_dict(self) -> Dict:
        """Convert to dictionary for CRD status."""
        return {
            'team': self.team_name,
            'businessUnit': self.business_unit,
            'totalCost': f'${float(self.total_cost):.2f}',
            'podCount': self.pod_count,
            'namespaces': self.namespaces,
            'avgCostPerPod': f'${float(self.avg_cost_per_pod):.2f}'
        }


@dataclass
class BusinessUnitCostSummary:
    """
    Aggregated costs for a business unit.

    Populated from user_business_unit tags.
    """
    business_unit: str
    total_cost: Decimal
    pod_count: int
    application_count: int
    namespace_count: int

    @property
    def percentage(self) -> float:
        """Will be calculated by collector based on total."""
        return 0.0

    def to_dict(self) -> Dict:
        """Convert to dictionary for CRD status."""
        return {
            'businessUnit': self.business_unit,
            'totalCost': f'${float(self.total_cost):.2f}',
            'podCount': self.pod_count,
            'applications': self.application_count,
            'namespaces': self.namespace_count
        }


@dataclass
class CostCenterCostSummary:
    """
    Aggregated costs for a cost center.

    Populated from user_cost_center tags.
    """
    cost_center: str
    business_unit: Optional[str]
    total_cost: Decimal
    pod_count: int
    application_count: int

    def to_dict(self) -> Dict:
        """Convert to dictionary for CRD status."""
        data = {
            'costCenter': self.cost_center,
            'totalCost': f'${float(self.total_cost):.2f}',
            'podCount': self.pod_count,
            'applications': self.application_count
        }
        if self.business_unit:
            data['businessUnit'] = self.business_unit
        return data


@dataclass
class ApplicationCostSummary:
    """
    Aggregated costs for an application.

    Populated from user_application tags.
    """
    application: str
    namespace: str
    cost_center: Optional[str]
    total_cost: Decimal
    pod_count: int
    workload_count: int

    def to_dict(self) -> Dict:
        """Convert to dictionary for CRD status."""
        data = {
            'application': self.application,
            'namespace': self.namespace,
            'totalCost': f'${float(self.total_cost):.2f}',
            'podCount': self.pod_count,
            'workloads': self.workload_count
        }
        if self.cost_center:
            data['costCenter'] = self.cost_center
        return data


@dataclass
class WorkloadTypeCostSummary:
    """
    Aggregated costs by workload type.

    Populated from aws_eks_workload_type tags (ReplicaSet, DaemonSet, StatefulSet, Job).
    """
    workload_type: str
    total_cost: Decimal
    pod_count: int
    unique_workloads: int

    def to_dict(self) -> Dict:
        """Convert to dictionary for CRD status."""
        return {
            'workloadType': self.workload_type,
            'totalCost': f'${float(self.total_cost):.2f}',
            'podCount': self.pod_count,
            'uniqueWorkloads': self.unique_workloads
        }


@dataclass
class PodCostSummary:
    """
    Cost summary for a single pod (for top-N reporting).
    """
    pod_name: str
    namespace: str
    total_cost: Decimal
    tagged: bool
    team: Optional[str] = None
    cost_center: Optional[str] = None
    reason: Optional[str] = None        # Why it's not tagged (if applicable)

    def to_dict(self) -> Dict:
        """Convert to dictionary for CRD status."""
        data = {
            'podName': self.pod_name,
            'namespace': self.namespace,
            'cost': f'${float(self.total_cost):.2f}',
            'tagged': self.tagged
        }
        if self.team:
            data['team'] = self.team
        if self.cost_center:
            data['costCenter'] = self.cost_center
        if self.reason:
            data['reason'] = self.reason
        return data


@dataclass
class AttributionSummary:
    """
    Summary of tagged vs. untagged costs.

    This is the key metric showing governance effectiveness!
    """
    tagged_cost: Decimal
    tagged_pod_count: int
    untagged_cost: Decimal
    untagged_pod_count: int

    @property
    def total_cost(self) -> Decimal:
        """Total cost across all pods."""
        return self.tagged_cost + self.untagged_cost

    @property
    def total_pods(self) -> int:
        """Total number of pods."""
        return self.tagged_pod_count + self.untagged_pod_count

    @property
    def attribution_rate(self) -> float:
        """Percentage of cost properly attributed (0-100)."""
        if self.total_cost == 0:
            return 0.0
        return float(self.tagged_cost / self.total_cost * 100)

    def to_dict(self) -> Dict:
        """Convert to dictionary for CRD status."""
        return {
            'taggedCost': f'${float(self.tagged_cost):.2f}',
            'taggedPodCount': self.tagged_pod_count,
            'untaggedCost': f'${float(self.untagged_cost):.2f}',
            'untaggedPodCount': self.untagged_pod_count,
            'attributionRate': round(self.attribution_rate, 1)
        }


@dataclass
class DailyCost:
    """Daily cost data point for trend analysis."""
    date: date
    cost: Decimal

    def to_dict(self) -> Dict:
        """Convert to dictionary for CRD status."""
        return {
            'date': self.date.isoformat(),
            'cost': f'${float(self.cost):.2f}'
        }


@dataclass
class NamespaceCostUtilization:
    """
    Cost utilization for a namespace — split cost vs unused cost.

    Shows how much of the reserved cost is actually used vs wasted.
    """
    namespace: str
    split_cost: Decimal                 # Cost of resources actually used
    unused_cost: Decimal                # Cost of resources requested but not used
    total_reserved_cost: Decimal        # split_cost + unused_cost
    cost_efficiency_pct: float          # (split_cost / total_reserved_cost) * 100

    def to_dict(self) -> Dict:
        """Convert to dictionary for CRD status."""
        return {
            'namespace': self.namespace,
            'splitCost': f'${float(self.split_cost):.2f}',
            'unusedCost': f'${float(self.unused_cost):.2f}',
            'totalReservedCost': f'${float(self.total_reserved_cost):.2f}',
            'costEfficiencyPct': round(self.cost_efficiency_pct, 1)
        }


@dataclass
class ClusterInfrastructureCostSummary:
    """
    Aggregated costs for cluster infrastructure components.

    Breaks down cluster operational costs by category and component.
    """
    category: str                           # "platform", "observability", "operations"
    component: str                          # "ebs-csi-driver", "prometheus", "karpenter", etc.
    namespace: str                          # Source namespace
    total_cost: Decimal
    pod_count: int
    description: str                        # Human-readable description

    def to_dict(self) -> Dict:
        """Convert to dictionary for CRD status."""
        return {
            'category': self.category,
            'component': self.component,
            'namespace': self.namespace,
            'totalCost': f'${float(self.total_cost):.2f}',
            'podCount': self.pod_count,
            'description': self.description
        }


@dataclass
class ClusterCostBreakdown:
    """
    High-level breakdown of application vs cluster infrastructure costs.

    Provides clear separation between:
    - Application costs (user workloads)
    - Cluster infrastructure costs (platform, observability, operations)
    """
    application_cost: Decimal
    application_pod_count: int
    cluster_infrastructure_cost: Decimal
    cluster_infrastructure_pod_count: int

    # Breakdown by infrastructure category
    by_infrastructure_component: List[ClusterInfrastructureCostSummary]

    @property
    def total_cost(self) -> Decimal:
        """Total cluster cost."""
        return self.application_cost + self.cluster_infrastructure_cost

    @property
    def total_pods(self) -> int:
        """Total pods."""
        return self.application_pod_count + self.cluster_infrastructure_pod_count

    @property
    def application_percentage(self) -> float:
        """Percentage of cost attributed to applications."""
        if self.total_cost == 0:
            return 0.0
        return float(self.application_cost / self.total_cost * 100)

    @property
    def infrastructure_percentage(self) -> float:
        """Percentage of cost attributed to cluster infrastructure."""
        if self.total_cost == 0:
            return 0.0
        return float(self.cluster_infrastructure_cost / self.total_cost * 100)

    def to_dict(self) -> Dict:
        """Convert to dictionary for CRD status."""
        # Calculate category totals
        category_totals = {}
        for component in self.by_infrastructure_component:
            if component.category not in category_totals:
                category_totals[component.category] = {'cost': Decimal('0'), 'pods': 0}
            category_totals[component.category]['cost'] += component.total_cost
            category_totals[component.category]['pods'] += component.pod_count

        return {
            'application': {
                'totalCost': f'${float(self.application_cost):.2f}',
                'podCount': self.application_pod_count,
                'percentage': round(self.application_percentage, 1)
            },
            'clusterInfrastructure': {
                'totalCost': f'${float(self.cluster_infrastructure_cost):.2f}',
                'podCount': self.cluster_infrastructure_pod_count,
                'percentage': round(self.infrastructure_percentage, 1),
                'byCategory': {
                    category: {
                        'totalCost': f'${float(totals["cost"]):.2f}',
                        'podCount': totals['pods'],
                        'percentage': round(float(totals['cost'] / self.cluster_infrastructure_cost * 100), 1) if self.cluster_infrastructure_cost > 0 else 0.0
                    }
                    for category, totals in category_totals.items()
                },
                'byComponent': [comp.to_dict() for comp in self.by_infrastructure_component]
            }
        }


@dataclass
class CostCollectionSummary:
    """
    Complete cost collection summary for a CostGovernance CRD.

    This is the top-level object that gets serialized to CRD status.
    """
    last_collection_time: datetime
    start_date: date
    end_date: date
    total_cost: Decimal
    pod_count: int

    # Namespace breakdown (always available)
    by_namespace: List[NamespaceCostSummary]

    # Attribution metrics (tagged vs untagged)
    attribution: AttributionSummary

    # Top cost pods
    top_cost_pods: List[PodCostSummary]

    # Daily trend
    daily_costs: List[DailyCost]

    # Team costs (only populated if tags available)
    by_team: List[TeamCostSummary] = field(default_factory=list)

    # Business unit costs (from user_business_unit tags)
    by_business_unit: List[BusinessUnitCostSummary] = field(default_factory=list)

    # Cost center costs (from user_cost_center tags)
    by_cost_center: List[CostCenterCostSummary] = field(default_factory=list)

    # Application costs (from user_application tags)
    by_application: List[ApplicationCostSummary] = field(default_factory=list)

    # Workload type costs (from aws_eks_workload_type tags)
    by_workload_type: List[WorkloadTypeCostSummary] = field(default_factory=list)

    # Cluster cost breakdown (application vs infrastructure)
    cluster_cost_breakdown: Optional['ClusterCostBreakdown'] = None

    # Cost utilization by namespace (split cost vs unused cost)
    cost_utilization: List[NamespaceCostUtilization] = field(default_factory=list)

    @property
    def avg_cost_per_pod(self) -> Decimal:
        """Average cost per pod."""
        return self.total_cost / self.pod_count if self.pod_count > 0 else Decimal('0')

    def to_dict(self) -> Dict:
        """
        Convert to dictionary for CRD status update.

        Returns nested structure ready for Kubernetes API.
        """
        result = {
            'lastCollectionTime': self.last_collection_time.isoformat(),
            'dateRange': {
                'start': self.start_date.isoformat(),
                'end': self.end_date.isoformat()
            },
            'summary': {
                'totalCost': f'${float(self.total_cost):.2f}',
                'podCount': self.pod_count,
                'avgCostPerPod': f'${float(self.avg_cost_per_pod):.2f}'
            },
            'byNamespace': [ns.to_dict() for ns in self.by_namespace],
            'attribution': self.attribution.to_dict(),
            'topCostPods': [pod.to_dict() for pod in self.top_cost_pods],
            'dailyCosts': [dc.to_dict() for dc in self.daily_costs]
        }

        # Add optional breakdowns if available
        if self.by_team:
            result['byTeam'] = [team.to_dict() for team in self.by_team]
        if self.by_business_unit:
            result['byBusinessUnit'] = [bu.to_dict() for bu in self.by_business_unit]
        if self.by_cost_center:
            result['byCostCenter'] = [cc.to_dict() for cc in self.by_cost_center]
        if self.by_application:
            result['byApplication'] = [app.to_dict() for app in self.by_application]
        if self.by_workload_type:
            result['byWorkloadType'] = [wt.to_dict() for wt in self.by_workload_type]
        if self.cluster_cost_breakdown:
            result['clusterCostBreakdown'] = self.cluster_cost_breakdown.to_dict()
        if self.cost_utilization:
            result['costUtilization'] = [cu.to_dict() for cu in self.cost_utilization]

        return result

    def __str__(self) -> str:
        """Human-readable summary."""
        return (
            f"Cost Collection Summary:\n"
            f"  Period: {self.start_date} to {self.end_date}\n"
            f"  Total Cost: ${float(self.total_cost):.2f}\n"
            f"  Pods: {self.pod_count}\n"
            f"  Avg Cost/Pod: ${float(self.avg_cost_per_pod):.2f}\n"
            f"  Attribution Rate: {self.attribution.attribution_rate:.1f}%\n"
            f"  Tagged Cost: ${float(self.attribution.tagged_cost):.2f} "
            f"({self.attribution.tagged_pod_count} pods)\n"
            f"  Untagged Cost: ${float(self.attribution.untagged_cost):.2f} "
            f"({self.attribution.untagged_pod_count} pods)"
        )
