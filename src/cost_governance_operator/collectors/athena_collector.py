"""
Athena collector for EKS cost data from CUR 2.0.

Queries AWS Cost and Usage Reports via Athena and aggregates costs
by namespace, team, and other dimensions.
"""

import logging
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

import boto3
from models.cost_data import (
    ApplicationCostSummary,
    AttributionSummary,
    BusinessUnitCostSummary,
    ClusterCostBreakdown,
    ClusterInfrastructureCostSummary,
    CostCenterCostSummary,
    CostCollectionSummary,
    DailyCost,
    NamespaceCostSummary,
    NamespaceCostUtilization,
    PodCostSummary,
    WorkloadTypeCostSummary,
)
from utils.athena_helper import (
    build_application_costs_query,
    build_attribution_summary_query,
    build_business_unit_costs_query,
    build_cluster_infrastructure_costs_query,
    build_cost_center_costs_query,
    build_cost_utilization_query,
    build_daily_cost_query,
    build_namespace_aggregation_query,
    build_top_cost_pods_query,
    build_total_cluster_cost_query,
    build_workload_type_costs_query,
    execute_athena_query,
    get_query_results,
)
from utils.cluster_infrastructure_config import (
    get_all_infrastructure_namespaces,
    get_component_config,
    get_component_name,
    is_cluster_infrastructure,
)

logger = logging.getLogger(__name__)


class AthenaCollector:
    """
    Collects EKS cost data from AWS Athena (CUR 2.0).

    Uses boto3 to query Cost and Usage Reports and aggregates data
    for display in CostGovernance CRD status.
    """

    def __init__(
        self,
        database: str,
        table: str,
        cluster_name: str,
        s3_output: str,
        aws_profile: Optional[str] = None,
        region: str = 'us-east-1'
    ):
        """
        Initialize Athena collector.

        Args:
            database: Athena database name (e.g., 'billingdata')
            table: CUR table name (e.g., 'data')
            cluster_name: EKS cluster name to filter
            s3_output: S3 location for Athena query results
            aws_profile: AWS profile name (None for Pod Identity)
            region: AWS region
        """
        self.database = database
        self.table = table
        self.cluster_name = cluster_name
        self.s3_output = s3_output
        self.region = region

        # Create boto3 session (with or without profile)
        if aws_profile:
            logger.info(f"Using AWS profile: {aws_profile}")
            self.session = boto3.Session(
                profile_name=aws_profile,
                region_name=region
            )
        else:
            logger.info("Using Pod Identity for AWS authentication")
            self.session = boto3.Session(region_name=region)

        # Create Athena client
        self.athena_client = self.session.client('athena')

    def collect_cost_summary(
        self,
        start_date: date,
        end_date: date
    ) -> Optional[CostCollectionSummary]:
        """
        Collect comprehensive cost summary for date range.

        This is the main entry point - executes multiple queries and
        aggregates results into a complete summary.

        Args:
            start_date: Start date for cost collection
            end_date: End date for cost collection

        Returns:
            CostCollectionSummary or None if collection fails
        """
        logger.info(
            f"Collecting cost data for cluster '{self.cluster_name}' "
            f"from {start_date} to {end_date}"
        )

        try:
            # Query 1: Total cluster cost (includes unused compute)
            total_cost = self._collect_total_cluster_cost(
                start_date, end_date
            )

            # Query 2: Namespace aggregation (always works)
            namespace_summaries = self._collect_namespace_costs(
                start_date, end_date
            )

            if not namespace_summaries:
                logger.warning("No namespace cost data found")
                return None

            # Query 2: Attribution summary (tagged vs untagged)
            attribution = self._collect_attribution_summary(
                start_date, end_date
            )

            # Query 3: Top cost pods
            top_pods = self._collect_top_cost_pods(
                start_date, end_date, limit=10
            )

            # Query 4: Daily costs
            daily_costs = self._collect_daily_costs(
                start_date, end_date
            )

            # Query 5: Business unit costs
            business_unit_costs = self._collect_business_unit_costs(
                start_date, end_date
            )

            # Query 6: Cost center costs
            cost_center_costs = self._collect_cost_center_costs(
                start_date, end_date
            )

            # Query 7: Application costs
            application_costs = self._collect_application_costs(
                start_date, end_date
            )

            # Query 8: Workload type costs
            workload_type_costs = self._collect_workload_type_costs(
                start_date, end_date
            )

            # Query 9: Cluster infrastructure breakdown
            cluster_breakdown = self._collect_cluster_infrastructure_breakdown(
                start_date, end_date, namespace_summaries
            )

            # Query 10: Cost utilization (split cost vs unused cost)
            cost_utilization = self._collect_cost_utilization(
                start_date, end_date
            )

            # Use total cluster cost from dedicated query (includes unused compute),
            # fall back to namespace sum if the query failed
            if total_cost is None:
                total_cost = sum(ns.total_cost for ns in namespace_summaries)
            total_pods = sum(ns.pod_count for ns in namespace_summaries)

            # Create summary
            summary = CostCollectionSummary(
                last_collection_time=datetime.now(),
                start_date=start_date,
                end_date=end_date,
                total_cost=total_cost,
                pod_count=total_pods,
                by_namespace=namespace_summaries,
                attribution=attribution,
                top_cost_pods=top_pods,
                daily_costs=daily_costs,
                by_team=[],  # Will be populated when tags are available
                by_business_unit=business_unit_costs,
                by_cost_center=cost_center_costs,
                by_application=application_costs,
                by_workload_type=workload_type_costs,
                cluster_cost_breakdown=cluster_breakdown,
                cost_utilization=cost_utilization
            )

            logger.info(f"Cost collection complete: {summary}")
            return summary

        except Exception as e:
            logger.error(f"Cost collection failed: {e}", exc_info=True)
            return None

    def _collect_total_cluster_cost(
        self,
        start_date: date,
        end_date: date
    ) -> Optional[Decimal]:
        """
        Collect total cluster cost including unused compute.

        Unlike the namespace aggregation, this captures all line items
        for the cluster — including unallocated CPU/memory.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            Total cluster cost as Decimal, or None if query fails
        """
        logger.info("Querying total cluster cost...")

        query = build_total_cluster_cost_query(
            self.database,
            self.table,
            self.cluster_name,
            start_date.isoformat(),
            end_date.isoformat()
        )

        query_id = execute_athena_query(
            self.athena_client,
            query,
            self.database,
            self.s3_output
        )

        if not query_id:
            logger.warning("Failed to execute total cluster cost query")
            return None

        results = get_query_results(self.athena_client, query_id)

        if not results:
            logger.warning("No total cluster cost data returned")
            return None

        try:
            total = Decimal(results[0].get('total_cluster_cost', '0') or '0')
            logger.info(f"Total cluster cost: ${float(total):.2f}")
            return total
        except Exception as e:
            logger.warning(f"Failed to parse total cluster cost: {e}")
            return None

    def _collect_namespace_costs(
        self,
        start_date: date,
        end_date: date
    ) -> List[NamespaceCostSummary]:
        """
        Collect costs aggregated by namespace.

        This query works even without tags - extracts namespace from ARN.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of NamespaceCostSummary objects
        """
        logger.info("Querying namespace costs...")

        # Build query
        query = build_namespace_aggregation_query(
            self.database,
            self.table,
            self.cluster_name,
            start_date.isoformat(),
            end_date.isoformat()
        )

        # Execute query
        query_id = execute_athena_query(
            self.athena_client,
            query,
            self.database,
            self.s3_output
        )

        if not query_id:
            logger.error("Failed to execute namespace aggregation query")
            return []

        # Get results
        results = get_query_results(self.athena_client, query_id)

        # Parse into NamespaceCostSummary objects
        summaries = []
        for row in results:
            try:
                namespace = row.get('namespace', 'unknown')
                pod_count = int(row.get('pod_count', 0))
                total_cost = Decimal(row.get('total_cost', '0'))
                tagged_pods = int(row.get('tagged_pods', 0))
                untagged_pods = int(row.get('untagged_pods', 0))

                summary = NamespaceCostSummary(
                    namespace=namespace,
                    total_cost=total_cost,
                    pod_count=pod_count,
                    tagged_pods=tagged_pods,
                    untagged_pods=untagged_pods
                )
                summaries.append(summary)

            except Exception as e:
                logger.warning(f"Failed to parse namespace row: {row}, error: {e}")
                continue

        logger.info(f"Found {len(summaries)} namespaces with costs")
        return summaries

    def _collect_attribution_summary(
        self,
        start_date: date,
        end_date: date
    ) -> AttributionSummary:
        """
        Collect attribution summary (tagged vs untagged).

        Key governance metric!

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            AttributionSummary object
        """
        logger.info("Querying attribution summary...")

        # Build query
        query = build_attribution_summary_query(
            self.database,
            self.table,
            self.cluster_name,
            start_date.isoformat(),
            end_date.isoformat()
        )

        # Execute query
        query_id = execute_athena_query(
            self.athena_client,
            query,
            self.database,
            self.s3_output
        )

        if not query_id:
            logger.error("Failed to execute attribution query")
            return AttributionSummary(
                tagged_cost=Decimal('0'),
                tagged_pod_count=0,
                untagged_cost=Decimal('0'),
                untagged_pod_count=0
            )

        # Get results
        results = get_query_results(self.athena_client, query_id)

        if not results:
            logger.warning("No attribution data returned")
            return AttributionSummary(
                tagged_cost=Decimal('0'),
                tagged_pod_count=0,
                untagged_cost=Decimal('0'),
                untagged_pod_count=0
            )

        # Parse result (should be single row)
        row = results[0]
        try:
            attribution = AttributionSummary(
                tagged_cost=Decimal(row.get('tagged_cost', '0') or '0'),
                tagged_pod_count=int(row.get('tagged_pods', 0) or 0),
                untagged_cost=Decimal(row.get('untagged_cost', '0') or '0'),
                untagged_pod_count=int(row.get('untagged_pods', 0) or 0)
            )

            logger.info(
                f"Attribution: {attribution.attribution_rate:.1f}% "
                f"({attribution.tagged_pod_count}/{attribution.total_pods} pods)"
            )
            return attribution

        except Exception as e:
            logger.error(f"Failed to parse attribution data: {e}")
            return AttributionSummary(
                tagged_cost=Decimal('0'),
                tagged_pod_count=0,
                untagged_cost=Decimal('0'),
                untagged_pod_count=0
            )

    def _collect_top_cost_pods(
        self,
        start_date: date,
        end_date: date,
        limit: int = 10
    ) -> List[PodCostSummary]:
        """
        Collect top N most expensive pods.

        Args:
            start_date: Start date
            end_date: End date
            limit: Number of top pods to return

        Returns:
            List of PodCostSummary objects
        """
        logger.info(f"Querying top {limit} cost pods...")

        # Build query
        query = build_top_cost_pods_query(
            self.database,
            self.table,
            self.cluster_name,
            start_date.isoformat(),
            end_date.isoformat(),
            limit
        )

        # Execute query
        query_id = execute_athena_query(
            self.athena_client,
            query,
            self.database,
            self.s3_output
        )

        if not query_id:
            logger.error("Failed to execute top pods query")
            return []

        # Get results
        results = get_query_results(self.athena_client, query_id)

        # Parse into PodCostSummary objects
        summaries = []
        for row in results:
            try:
                namespace = row.get('namespace', 'unknown')
                pod_name = row.get('pod_name', 'unknown')
                total_cost = Decimal(row.get('total_cost', '0'))
                team = row.get('team')
                cost_center = row.get('cost_center')

                # Determine if tagged and reason if not
                tagged = team is not None and cost_center is not None
                reason = None
                if not tagged:
                    if namespace in ['kube-system', 'kube-public', 'kube-node-lease']:
                        reason = "System pod - no cost labels"
                    else:
                        reason = "Missing cost governance labels"

                summary = PodCostSummary(
                    pod_name=pod_name,
                    namespace=namespace,
                    total_cost=total_cost,
                    tagged=tagged,
                    team=team,
                    cost_center=cost_center,
                    reason=reason
                )
                summaries.append(summary)

            except Exception as e:
                logger.warning(f"Failed to parse top pod row: {row}, error: {e}")
                continue

        logger.info(f"Found {len(summaries)} top cost pods")
        return summaries

    def _collect_daily_costs(
        self,
        start_date: date,
        end_date: date
    ) -> List[DailyCost]:
        """
        Collect daily cost trends.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of DailyCost objects
        """
        logger.info("Querying daily costs...")

        # Build query
        query = build_daily_cost_query(
            self.database,
            self.table,
            self.cluster_name,
            start_date.isoformat(),
            end_date.isoformat()
        )

        # Execute query
        query_id = execute_athena_query(
            self.athena_client,
            query,
            self.database,
            self.s3_output
        )

        if not query_id:
            logger.error("Failed to execute daily costs query")
            return []

        # Get results
        results = get_query_results(self.athena_client, query_id)

        # Parse into DailyCost objects
        daily_costs = []
        for row in results:
            try:
                usage_date = datetime.fromisoformat(row['usage_date']).date()
                daily_cost = Decimal(row.get('daily_cost', '0'))

                dc = DailyCost(
                    date=usage_date,
                    cost=daily_cost
                )
                daily_costs.append(dc)

            except Exception as e:
                logger.warning(f"Failed to parse daily cost row: {row}, error: {e}")
                continue

        logger.info(f"Found {len(daily_costs)} days of cost data")
        return daily_costs

    def _collect_business_unit_costs(
        self,
        start_date: date,
        end_date: date
    ) -> List[BusinessUnitCostSummary]:
        """
        Collect costs aggregated by business unit.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of BusinessUnitCostSummary objects
        """
        logger.info("Querying business unit costs...")

        # Build query
        query = build_business_unit_costs_query(
            self.database,
            self.table,
            self.cluster_name,
            start_date.isoformat(),
            end_date.isoformat()
        )

        # Execute query
        query_id = execute_athena_query(
            self.athena_client,
            query,
            self.database,
            self.s3_output
        )

        if not query_id:
            logger.warning("Failed to execute business unit query")
            return []

        # Get results
        results = get_query_results(self.athena_client, query_id)

        # Parse into BusinessUnitCostSummary objects
        summaries = []
        for row in results:
            try:
                business_unit = row.get('business_unit')
                if not business_unit:
                    continue

                summary = BusinessUnitCostSummary(
                    business_unit=business_unit,
                    total_cost=Decimal(row.get('total_cost', '0')),
                    pod_count=int(row.get('pod_count', 0)),
                    application_count=int(row.get('application_count', 0)),
                    namespace_count=int(row.get('namespace_count', 0))
                )
                summaries.append(summary)

            except Exception as e:
                logger.warning(f"Failed to parse business unit row: {row}, error: {e}")
                continue

        logger.info(f"Found {len(summaries)} business units with costs")
        return summaries

    def _collect_cost_center_costs(
        self,
        start_date: date,
        end_date: date
    ) -> List[CostCenterCostSummary]:
        """
        Collect costs aggregated by cost center.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of CostCenterCostSummary objects
        """
        logger.info("Querying cost center costs...")

        # Build query
        query = build_cost_center_costs_query(
            self.database,
            self.table,
            self.cluster_name,
            start_date.isoformat(),
            end_date.isoformat()
        )

        # Execute query
        query_id = execute_athena_query(
            self.athena_client,
            query,
            self.database,
            self.s3_output
        )

        if not query_id:
            logger.warning("Failed to execute cost center query")
            return []

        # Get results
        results = get_query_results(self.athena_client, query_id)

        # Parse into CostCenterCostSummary objects
        summaries = []
        for row in results:
            try:
                cost_center = row.get('cost_center')
                if not cost_center:
                    continue

                summary = CostCenterCostSummary(
                    cost_center=cost_center,
                    business_unit=row.get('business_unit'),
                    total_cost=Decimal(row.get('total_cost', '0')),
                    pod_count=int(row.get('pod_count', 0)),
                    application_count=int(row.get('application_count', 0))
                )
                summaries.append(summary)

            except Exception as e:
                logger.warning(f"Failed to parse cost center row: {row}, error: {e}")
                continue

        logger.info(f"Found {len(summaries)} cost centers with costs")
        return summaries

    def _collect_application_costs(
        self,
        start_date: date,
        end_date: date
    ) -> List[ApplicationCostSummary]:
        """
        Collect costs aggregated by application.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of ApplicationCostSummary objects
        """
        logger.info("Querying application costs...")

        # Build query
        query = build_application_costs_query(
            self.database,
            self.table,
            self.cluster_name,
            start_date.isoformat(),
            end_date.isoformat()
        )

        # Execute query
        query_id = execute_athena_query(
            self.athena_client,
            query,
            self.database,
            self.s3_output
        )

        if not query_id:
            logger.warning("Failed to execute application query")
            return []

        # Get results
        results = get_query_results(self.athena_client, query_id)

        # Parse into ApplicationCostSummary objects
        summaries = []
        for row in results:
            try:
                application = row.get('application')
                namespace = row.get('namespace')
                if not application or not namespace:
                    continue

                summary = ApplicationCostSummary(
                    application=application,
                    namespace=namespace,
                    cost_center=row.get('cost_center'),
                    total_cost=Decimal(row.get('total_cost', '0')),
                    pod_count=int(row.get('pod_count', 0)),
                    workload_count=int(row.get('workload_count', 0))
                )
                summaries.append(summary)

            except Exception as e:
                logger.warning(f"Failed to parse application row: {row}, error: {e}")
                continue

        logger.info(f"Found {len(summaries)} applications with costs")
        return summaries

    def _collect_workload_type_costs(
        self,
        start_date: date,
        end_date: date
    ) -> List[WorkloadTypeCostSummary]:
        """
        Collect costs aggregated by workload type.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of WorkloadTypeCostSummary objects
        """
        logger.info("Querying workload type costs...")

        # Build query
        query = build_workload_type_costs_query(
            self.database,
            self.table,
            self.cluster_name,
            start_date.isoformat(),
            end_date.isoformat()
        )

        # Execute query
        query_id = execute_athena_query(
            self.athena_client,
            query,
            self.database,
            self.s3_output
        )

        if not query_id:
            logger.warning("Failed to execute workload type query")
            return []

        # Get results
        results = get_query_results(self.athena_client, query_id)

        # Parse into WorkloadTypeCostSummary objects
        summaries = []
        for row in results:
            try:
                workload_type = row.get('workload_type')
                if not workload_type:
                    continue

                summary = WorkloadTypeCostSummary(
                    workload_type=workload_type,
                    total_cost=Decimal(row.get('total_cost', '0')),
                    pod_count=int(row.get('pod_count', 0)),
                    unique_workloads=int(row.get('unique_workloads', 0))
                )
                summaries.append(summary)

            except Exception as e:
                logger.warning(f"Failed to parse workload type row: {row}, error: {e}")
                continue

        logger.info(f"Found {len(summaries)} workload types with costs")
        return summaries

    def _collect_cost_utilization(
        self,
        start_date: date,
        end_date: date
    ) -> List[NamespaceCostUtilization]:
        """
        Collect cost utilization (split cost vs unused cost) by namespace.

        Shows how much of the reserved cost is actually used vs wasted.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of NamespaceCostUtilization objects
        """
        logger.info("Querying cost utilization by namespace...")

        query = build_cost_utilization_query(
            self.database,
            self.table,
            self.cluster_name,
            start_date.isoformat(),
            end_date.isoformat()
        )

        query_id = execute_athena_query(
            self.athena_client,
            query,
            self.database,
            self.s3_output
        )

        if not query_id:
            logger.warning("Failed to execute cost utilization query")
            return []

        results = get_query_results(self.athena_client, query_id)

        utilizations = []
        for row in results:
            try:
                namespace = row.get('namespace')
                if not namespace:
                    continue

                utilization = NamespaceCostUtilization(
                    namespace=namespace,
                    split_cost=Decimal(row.get('split_cost', '0') or '0'),
                    unused_cost=Decimal(row.get('unused_cost', '0') or '0'),
                    total_reserved_cost=Decimal(row.get('total_reserved_cost', '0') or '0'),
                    cost_efficiency_pct=float(row.get('cost_efficiency_pct', '0') or '0')
                )
                utilizations.append(utilization)

            except Exception as e:
                logger.warning(f"Failed to parse cost utilization row: {row}, error: {e}")
                continue

        logger.info(f"Found {len(utilizations)} namespaces with cost utilization data")
        return utilizations

    def _collect_cluster_infrastructure_breakdown(
        self,
        start_date: date,
        end_date: date,
        namespace_summaries: List[NamespaceCostSummary]
    ) -> Optional[ClusterCostBreakdown]:
        """
        Collect and categorize cluster infrastructure costs.

        Queries pod-level costs for infrastructure namespaces and categorizes
        them by component (e.g., kube-proxy, prometheus, karpenter).

        Args:
            start_date: Start date
            end_date: End date
            namespace_summaries: Pre-computed namespace summaries for totals

        Returns:
            ClusterCostBreakdown object or None if query fails
        """
        logger.info("Analyzing cluster infrastructure costs...")

        # Get list of infrastructure namespaces
        infra_namespaces = get_all_infrastructure_namespaces()

        # Build and execute query
        query = build_cluster_infrastructure_costs_query(
            self.database,
            self.table,
            self.cluster_name,
            start_date.isoformat(),
            end_date.isoformat(),
            infra_namespaces
        )

        query_id = execute_athena_query(
            self.athena_client,
            query,
            self.database,
            self.s3_output
        )

        if not query_id:
            logger.warning("Failed to execute cluster infrastructure query")
            return None

        # Get pod-level results
        results = get_query_results(self.athena_client, query_id)

        # Aggregate by component
        component_costs = defaultdict(lambda: {'cost': Decimal('0'), 'pods': set()})

        for row in results:
            try:
                namespace = row.get('namespace', 'unknown')
                pod_name = row.get('pod_name', '')
                cost = Decimal(row.get('total_cost', '0'))

                # Get component config
                config = get_component_config(pod_name, namespace)

                if config:
                    # Known component - use config
                    component_name = get_component_name(pod_name)
                    component_key = (namespace, component_name, config.category, config.description)
                else:
                    # Unknown component - generic categorization
                    component_name = get_component_name(pod_name)
                    category = 'platform' if namespace == 'kube-system' else 'unknown'
                    description = f"Other {namespace} component"
                    component_key = (namespace, component_name, category, description)

                component_costs[component_key]['cost'] += cost
                component_costs[component_key]['pods'].add(pod_name)

            except Exception as e:
                logger.warning(f"Failed to parse infrastructure pod row: {row}, error: {e}")
                continue

        # Convert to ClusterInfrastructureCostSummary objects
        infrastructure_components = []
        for (namespace, component, category, description), data in component_costs.items():
            summary = ClusterInfrastructureCostSummary(
                category=category,
                component=component,
                namespace=namespace,
                total_cost=data['cost'],
                pod_count=len(data['pods']),
                description=description
            )
            infrastructure_components.append(summary)

        # Sort by cost descending
        infrastructure_components.sort(key=lambda x: x.total_cost, reverse=True)

        # Calculate application vs infrastructure totals from namespace summaries
        infra_cost = Decimal('0')
        infra_pod_count = 0
        app_cost = Decimal('0')
        app_pod_count = 0

        for ns_summary in namespace_summaries:
            if is_cluster_infrastructure(ns_summary.namespace):
                infra_cost += ns_summary.total_cost
                infra_pod_count += ns_summary.pod_count
            else:
                app_cost += ns_summary.total_cost
                app_pod_count += ns_summary.pod_count

        # Create breakdown
        breakdown = ClusterCostBreakdown(
            application_cost=app_cost,
            application_pod_count=app_pod_count,
            cluster_infrastructure_cost=infra_cost,
            cluster_infrastructure_pod_count=infra_pod_count,
            by_infrastructure_component=infrastructure_components
        )

        logger.info(
            f"Cluster breakdown: Application {app_cost:.2f} ({app_pod_count} pods), "
            f"Infrastructure {infra_cost:.2f} ({infra_pod_count} pods) - "
            f"{len(infrastructure_components)} components"
        )

        return breakdown
