"""
Athena query utilities for CUR data collection.

Low-level functions for executing Athena queries and parsing results.
"""

import logging
import time
from typing import Dict, List, Optional

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def execute_athena_query(
    athena_client,
    query: str,
    database: str,
    s3_output: str,
    max_wait_seconds: int = 60
) -> Optional[str]:
    """
    Execute an Athena query and wait for completion.

    Args:
        athena_client: boto3 Athena client
        query: SQL query string
        database: Athena database name
        s3_output: S3 location for query results
        max_wait_seconds: Maximum time to wait for query completion

    Returns:
        query_execution_id if successful, None if failed
    """
    try:
        # Start query execution
        response = athena_client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={'Database': database},
            ResultConfiguration={'OutputLocation': s3_output}
        )

        query_execution_id = response['QueryExecutionId']
        logger.info(f"Started Athena query: {query_execution_id}")

        # Wait for query to complete
        wait_interval = 2  # seconds
        elapsed = 0

        while elapsed < max_wait_seconds:
            response = athena_client.get_query_execution(
                QueryExecutionId=query_execution_id
            )

            status = response['QueryExecution']['Status']['State']

            if status == 'SUCCEEDED':
                logger.info(f"Query {query_execution_id} succeeded")
                return query_execution_id
            elif status in ['FAILED', 'CANCELLED']:
                reason = response['QueryExecution']['Status'].get(
                    'StateChangeReason', 'Unknown'
                )
                logger.error(f"Query {query_execution_id} failed: {reason}")
                return None

            time.sleep(wait_interval)
            elapsed += wait_interval

        logger.warning(f"Query {query_execution_id} timed out after {max_wait_seconds}s")
        return None

    except ClientError as e:
        logger.error(f"Athena query execution failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error executing Athena query: {e}", exc_info=True)
        return None


def get_query_results(
    athena_client,
    query_execution_id: str,
    max_results: int = 1000
) -> List[Dict[str, str]]:
    """
    Get query results from Athena.

    Args:
        athena_client: boto3 Athena client
        query_execution_id: Query execution ID
        max_results: Maximum number of results per page

    Returns:
        List of rows (each row is a dict mapping column name to value)
    """
    try:
        # Get results using pagination
        paginator = athena_client.get_paginator('get_query_results')
        page_iterator = paginator.paginate(
            QueryExecutionId=query_execution_id,
            PaginationConfig={'PageSize': max_results}
        )

        results = []
        column_names = None

        for page in page_iterator:
            rows = page['ResultSet']['Rows']

            # First row is column headers
            if column_names is None and rows:
                column_names = [col['VarCharValue'] for col in rows[0]['Data']]
                rows = rows[1:]  # Skip header row

            # Parse data rows
            for row in rows:
                row_data = {}
                for i, col in enumerate(row['Data']):
                    col_name = column_names[i] if column_names else f'col_{i}'
                    # Handle NULL values
                    row_data[col_name] = col.get('VarCharValue', None)
                results.append(row_data)

        logger.info(f"Retrieved {len(results)} rows from query {query_execution_id}")
        return results

    except ClientError as e:
        logger.error(f"Failed to get query results: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting query results: {e}", exc_info=True)
        return []


def deprecated_parse_resource_id(resource_id: str) -> Dict[str, str]:
    """
    Parse EKS resource ID (ARN) to extract components.

    Example resource_id:
    arn:aws:eks:us-east-1:123456789012:cluster/my-cluster/pod/namespace/pod-name/uuid
                                                                   ^^^^^^^^^  ^^^^^^^^
                                                                   namespace  pod-name

    Args:
        resource_id: EKS pod ARN

    Returns:
        Dict with keys: cluster, namespace, pod_name, uuid
        Returns 'unknown' for fields that can't be parsed
    """
    try:
        # Pattern: .../cluster/{cluster}/pod/{namespace}/{pod-name}/{uuid}
        # Split by '/' to extract components
        parts = resource_id.split('/')

        # Find the 'pod' marker
        if 'pod' not in parts:
            logger.warning(f"Resource ID doesn't contain 'pod': {resource_id}")
            return {
                'cluster': 'unknown',
                'namespace': 'unknown',
                'pod_name': 'unknown',
                'uuid': 'unknown'
            }

        pod_index = parts.index('pod')

        # Extract components after 'pod/'
        cluster = parts[pod_index - 1] if pod_index > 0 else 'unknown'
        namespace = parts[pod_index + 1] if len(parts) > pod_index + 1 else 'unknown'
        pod_name = parts[pod_index + 2] if len(parts) > pod_index + 2 else 'unknown'
        uuid = parts[pod_index + 3] if len(parts) > pod_index + 3 else 'unknown'

        return {
            'cluster': cluster,
            'namespace': namespace,
            'pod_name': pod_name,
            'uuid': uuid
        }

    except Exception as e:
        logger.warning(f"Failed to parse resource_id: {resource_id}, error: {e}")
        return {
            'cluster': 'unknown',
            'namespace': 'unknown',
            'pod_name': 'unknown',
            'uuid': 'unknown'
        }


def deprecated_build_eks_cost_query(
    database: str,
    table: str,
    cluster_name: str,
    start_date: str,
    end_date: str,
    extract_tags: bool = True
) -> str:
    """
    Build SQL query to fetch EKS pod costs from CUR.

    Args:
        database: Athena database name
        table: CUR table name
        cluster_name: EKS cluster name to filter
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        extract_tags: Whether to extract cost governance tags

    Returns:
        SQL query string
    """
    # Base columns
    columns = [
        "line_item_resource_id",
        "line_item_usage_start_date",
        "split_line_item_split_cost as cost"
    ]

    # Add tag columns if requested
    if extract_tags:
        tag_columns = [
            "resource_tags['cost-center'] as cost_center",
            "resource_tags['business-unit'] as business_unit",
            "resource_tags['team'] as team",
            "resource_tags['application'] as application",
            "resource_tags['environment'] as environment"
        ]
        columns.extend(tag_columns)

    query = f"""
    SELECT
        {', '.join(columns)}
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND split_line_item_split_cost > 0
        AND line_item_resource_id LIKE '%{cluster_name}%'
        AND line_item_resource_id LIKE '%pod%'
        AND line_item_usage_start_date >= DATE('{start_date}')
        AND line_item_usage_start_date < DATE('{end_date}')
    ORDER BY line_item_usage_start_date DESC
    """

    return query


def build_namespace_aggregation_query(
    database: str,
    table: str,
    cluster_name: str,
    start_date: str,
    end_date: str
) -> str:
    """
    Build SQL query to aggregate costs by namespace.

    Uses aws_eks_namespace tag (better than ARN parsing).

    Args:
        database: Athena database name
        table: CUR table name
        cluster_name: EKS cluster name
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        SQL query string
    """
    query = f"""
    SELECT
        resource_tags['aws_eks_namespace'] as namespace,
        COUNT(DISTINCT line_item_resource_id) as pod_count,
        SUM(COALESCE(split_line_item_split_cost, line_item_unblended_cost)) as total_cost,
        COUNT(DISTINCT CASE WHEN resource_tags['user_cost_center'] IS NOT NULL THEN line_item_resource_id END) as tagged_pods,
        COUNT(DISTINCT CASE WHEN resource_tags['user_cost_center'] IS NULL THEN line_item_resource_id END) as untagged_pods
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND resource_tags['aws_eks_cluster_name'] = '{cluster_name}'
        AND resource_tags['aws_eks_namespace'] IS NOT NULL
        AND DATE(line_item_usage_start_date) >= DATE('{start_date}')
        AND DATE(line_item_usage_start_date) < DATE('{end_date}')
    GROUP BY resource_tags['aws_eks_namespace']
    ORDER BY total_cost DESC
    """

    return query


def build_attribution_summary_query(
    database: str,
    table: str,
    cluster_name: str,
    start_date: str,
    end_date: str
) -> str:
    """
    Build SQL query to calculate tagged vs untagged costs.

    Key governance metric! Uses user_cost_center as the indicator of proper tagging.

    Args:
        database: Athena database name
        table: CUR table name
        cluster_name: EKS cluster name
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        SQL query string
    """
    query = f"""
    SELECT
        COUNT(DISTINCT CASE WHEN resource_tags['user_cost_center'] IS NOT NULL THEN line_item_resource_id END) as tagged_pods,
        COUNT(DISTINCT CASE WHEN resource_tags['user_cost_center'] IS NULL THEN line_item_resource_id END) as untagged_pods,
        SUM(CASE WHEN resource_tags['user_cost_center'] IS NOT NULL THEN COALESCE(split_line_item_split_cost, line_item_unblended_cost) ELSE 0 END) as tagged_cost,
        SUM(CASE WHEN resource_tags['user_cost_center'] IS NULL THEN COALESCE(split_line_item_split_cost, line_item_unblended_cost) ELSE 0 END) as untagged_cost
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND resource_tags['aws_eks_cluster_name'] = '{cluster_name}'
        AND DATE(line_item_usage_start_date) >= DATE('{start_date}')
        AND DATE(line_item_usage_start_date) < DATE('{end_date}')
    """

    return query


def build_top_cost_pods_query(
    database: str,
    table: str,
    cluster_name: str,
    start_date: str,
    end_date: str,
    limit: int = 10
) -> str:
    """
    Build SQL query to get top N most expensive pods.

    Args:
        database: Athena database name
        table: CUR table name
        cluster_name: EKS cluster name
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        limit: Number of top pods to return

    Returns:
        SQL query string
    """
    query = f"""
    SELECT
        line_item_resource_id,
        MAX(resource_tags['aws_eks_namespace']) as namespace,
        MAX(resource_tags['aws_eks_workload_name']) as pod_name,
        SUM(COALESCE(split_line_item_split_cost, line_item_unblended_cost)) as total_cost,
        MAX(resource_tags['user_application']) as team,
        MAX(resource_tags['user_cost_center']) as cost_center
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND resource_tags['aws_eks_cluster_name'] = '{cluster_name}'
        AND DATE(line_item_usage_start_date) >= DATE('{start_date}')
        AND DATE(line_item_usage_start_date) < DATE('{end_date}')
    GROUP BY line_item_resource_id
    ORDER BY total_cost DESC
    LIMIT {limit}
    """

    return query


def build_daily_cost_query(
    database: str,
    table: str,
    cluster_name: str,
    start_date: str,
    end_date: str
) -> str:
    """
    Build SQL query to get daily cost trends.

    Args:
        database: Athena database name
        table: CUR table name
        cluster_name: EKS cluster name
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        SQL query string
    """
    query = f"""
    SELECT
        DATE(line_item_usage_start_date) as usage_date,
        SUM(
            COALESCE(split_line_item_split_cost, 0) +
            COALESCE(split_line_item_unused_cost, 0) +
            CASE WHEN line_item_operation = 'CreateOperation' THEN line_item_unblended_cost ELSE 0 END
        ) as daily_cost
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND (
            resource_tags['aws_eks_cluster_name'] = '{cluster_name}'
            OR (line_item_operation = 'CreateOperation' AND line_item_resource_id LIKE '%{cluster_name}%')
        )
        AND DATE(line_item_usage_start_date) >= DATE('{start_date}')
        AND DATE(line_item_usage_start_date) < DATE('{end_date}')
    GROUP BY DATE(line_item_usage_start_date)
    ORDER BY usage_date ASC
    """

    return query


def build_business_unit_costs_query(
    database: str,
    table: str,
    cluster_name: str,
    start_date: str,
    end_date: str
) -> str:
    """
    Build SQL query to aggregate costs by business unit.

    Uses user_business_unit tags from CUR 2.0.

    Args:
        database: Athena database name
        table: CUR table name
        cluster_name: EKS cluster name
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        SQL query string
    """
    query = f"""
    SELECT
        resource_tags['user_business_unit'] as business_unit,
        COUNT(DISTINCT line_item_resource_id) as pod_count,
        COUNT(DISTINCT resource_tags['user_application']) as application_count,
        COUNT(DISTINCT resource_tags['aws_eks_namespace']) as namespace_count,
        SUM(COALESCE(split_line_item_split_cost, line_item_unblended_cost)) as total_cost
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND resource_tags['aws_eks_cluster_name'] = '{cluster_name}'
        AND resource_tags['user_business_unit'] IS NOT NULL
        AND DATE(line_item_usage_start_date) >= DATE('{start_date}')
        AND DATE(line_item_usage_start_date) < DATE('{end_date}')
    GROUP BY resource_tags['user_business_unit']
    ORDER BY total_cost DESC
    """

    return query


def build_cost_center_costs_query(
    database: str,
    table: str,
    cluster_name: str,
    start_date: str,
    end_date: str
) -> str:
    """
    Build SQL query to aggregate costs by cost center.

    Uses user_cost_center tags from CUR 2.0.

    Args:
        database: Athena database name
        table: CUR table name
        cluster_name: EKS cluster name
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        SQL query string
    """
    query = f"""
    SELECT
        resource_tags['user_cost_center'] as cost_center,
        resource_tags['user_business_unit'] as business_unit,
        COUNT(DISTINCT line_item_resource_id) as pod_count,
        COUNT(DISTINCT resource_tags['user_application']) as application_count,
        SUM(COALESCE(split_line_item_split_cost, line_item_unblended_cost)) as total_cost
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND resource_tags['aws_eks_cluster_name'] = '{cluster_name}'
        AND resource_tags['user_cost_center'] IS NOT NULL
        AND DATE(line_item_usage_start_date) >= DATE('{start_date}')
        AND DATE(line_item_usage_start_date) < DATE('{end_date}')
    GROUP BY
        resource_tags['user_cost_center'],
        resource_tags['user_business_unit']
    ORDER BY total_cost DESC
    """

    return query


def build_application_costs_query(
    database: str,
    table: str,
    cluster_name: str,
    start_date: str,
    end_date: str
) -> str:
    """
    Build SQL query to aggregate costs by application.

    Uses user_application tags from CUR 2.0.

    Args:
        database: Athena database name
        table: CUR table name
        cluster_name: EKS cluster name
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        SQL query string
    """
    query = f"""
    SELECT
        resource_tags['user_application'] as application,
        resource_tags['aws_eks_namespace'] as namespace,
        resource_tags['user_cost_center'] as cost_center,
        COUNT(DISTINCT line_item_resource_id) as pod_count,
        COUNT(DISTINCT resource_tags['aws_eks_workload_name']) as workload_count,
        SUM(COALESCE(split_line_item_split_cost, line_item_unblended_cost)) as total_cost
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND resource_tags['aws_eks_cluster_name'] = '{cluster_name}'
        AND resource_tags['user_application'] IS NOT NULL
        AND DATE(line_item_usage_start_date) >= DATE('{start_date}')
        AND DATE(line_item_usage_start_date) < DATE('{end_date}')
    GROUP BY
        resource_tags['user_application'],
        resource_tags['aws_eks_namespace'],
        resource_tags['user_cost_center']
    ORDER BY total_cost DESC
    """

    return query


def build_workload_type_costs_query(
    database: str,
    table: str,
    cluster_name: str,
    start_date: str,
    end_date: str
) -> str:
    """
    Build SQL query to aggregate costs by workload type.

    Uses aws_eks_workload_type tags from CUR 2.0 (ReplicaSet, DaemonSet, StatefulSet, Job).

    Args:
        database: Athena database name
        table: CUR table name
        cluster_name: EKS cluster name
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        SQL query string
    """
    query = f"""
    SELECT
        resource_tags['aws_eks_workload_type'] as workload_type,
        COUNT(DISTINCT line_item_resource_id) as pod_count,
        COUNT(DISTINCT resource_tags['aws_eks_workload_name']) as unique_workloads,
        SUM(COALESCE(split_line_item_split_cost, line_item_unblended_cost)) as total_cost
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND resource_tags['aws_eks_cluster_name'] = '{cluster_name}'
        AND resource_tags['aws_eks_workload_type'] IS NOT NULL
        AND DATE(line_item_usage_start_date) >= DATE('{start_date}')
        AND DATE(line_item_usage_start_date) < DATE('{end_date}')
    GROUP BY resource_tags['aws_eks_workload_type']
    ORDER BY total_cost DESC
    """

    return query


def build_cost_utilization_query(
    database: str,
    table: str,
    cluster_name: str,
    start_date: str,
    end_date: str
) -> str:
    """
    Build SQL query to get cost utilization (split cost vs unused cost) by namespace.

    Shows how much of the reserved cost is actually used vs wasted.

    Args:
        database: Athena database name
        table: CUR table name
        cluster_name: EKS cluster name
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        SQL query string
    """
    query = f"""
    SELECT
        resource_tags['aws_eks_namespace'] AS namespace,
        ROUND(SUM(split_line_item_split_cost), 4) AS split_cost,
        ROUND(SUM(split_line_item_unused_cost), 4) AS unused_cost,
        ROUND(SUM(split_line_item_split_cost) + SUM(split_line_item_unused_cost), 4) AS total_reserved_cost,
        ROUND(100.0 * SUM(split_line_item_split_cost) / NULLIF(SUM(split_line_item_split_cost) + SUM(split_line_item_unused_cost), 0), 1) AS cost_efficiency_pct
    FROM {database}.{table}
    WHERE
        resource_tags['aws_eks_cluster_name'] = '{cluster_name}'
        AND resource_tags['aws_eks_namespace'] IS NOT NULL
        AND line_item_operation = 'EKSPod-EC2'
        AND DATE(line_item_usage_start_date) >= DATE('{start_date}')
        AND DATE(line_item_usage_start_date) < DATE('{end_date}')
    GROUP BY resource_tags['aws_eks_namespace']
    ORDER BY unused_cost DESC
    """

    return query


def build_total_cluster_cost_query(
    database: str,
    table: str,
    cluster_name: str,
    start_date: str,
    end_date: str
) -> str:
    """
    Build SQL query to get total cluster cost.

    Includes:
    - split_line_item_split_cost: cost allocated to pods
    - split_line_item_unused_cost: cost of unallocated node capacity
    - EKS control plane cost (CreateOperation at $0.10/hr)

    Args:
        database: Athena database name
        table: CUR table name
        cluster_name: EKS cluster name
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        SQL query string
    """
    query = f"""
    SELECT
        '{cluster_name}' AS cluster_name,
        SUM(
            COALESCE(split_line_item_split_cost, 0) +
            COALESCE(split_line_item_unused_cost, 0) +
            CASE WHEN line_item_operation = 'CreateOperation' THEN line_item_unblended_cost ELSE 0 END
        ) AS total_cluster_cost
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND (
            resource_tags['aws_eks_cluster_name'] = '{cluster_name}'
            OR (line_item_operation = 'CreateOperation' AND line_item_resource_id LIKE '%{cluster_name}%')
        )
        AND DATE(line_item_usage_start_date) >= DATE('{start_date}')
        AND DATE(line_item_usage_start_date) < DATE('{end_date}')
    """

    return query


def build_cluster_infrastructure_costs_query(
    database: str,
    table: str,
    cluster_name: str,
    start_date: str,
    end_date: str,
    infrastructure_namespaces: List[str]
) -> str:
    """
    Build SQL query to get detailed costs for cluster infrastructure pods.

    Retrieves pod-level cost data for system namespaces (kube-system, monitoring, karpenter, etc.)
    so we can categorize them by component.

    Args:
        database: Athena database name
        table: CUR table name
        cluster_name: EKS cluster name
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        infrastructure_namespaces: List of namespace names to include

    Returns:
        SQL query string
    """
    # Build namespace filter
    namespace_filter = " OR ".join([
        f"resource_tags['aws_eks_namespace'] = '{ns}'"
        for ns in infrastructure_namespaces
    ])

    query = f"""
    SELECT
        resource_tags['aws_eks_namespace'] as namespace,
        resource_tags['aws_eks_workload_name'] as pod_name,
        SUM(COALESCE(split_line_item_split_cost, line_item_unblended_cost)) as total_cost
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND resource_tags['aws_eks_cluster_name'] = '{cluster_name}'
        AND ({namespace_filter})
        AND DATE(line_item_usage_start_date) >= DATE('{start_date}')
        AND DATE(line_item_usage_start_date) < DATE('{end_date}')
    GROUP BY
        resource_tags['aws_eks_namespace'],
        resource_tags['aws_eks_workload_name']
    ORDER BY total_cost DESC
    """

    return query
