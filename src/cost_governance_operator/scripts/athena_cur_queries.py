# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#!/usr/bin/env python3
"""
Athena CUR 2.0 Query Examples
Demonstrates various cost analysis queries for EKS using CUR 2.0 data.
"""

import sys
import time
from datetime import datetime, timedelta

import boto3

# Configuration
AWS_REGION = 'us-east-1'
DATABASE = 'cur_database'
TABLE = 'data'
OUTPUT_LOCATION = 's3://athena-results-783837106602-us-east-1-an/'
CLUSTER_NAME = 'cost-demo-eks-cluster'


class AthenaQueryRunner:
    def __init__(self, region, database, output_location):
        self.client = boto3.client('athena', region_name=region)
        self.database = database
        self.output_location = output_location

    def execute_query(self, query, description=""):
        """Execute Athena query and return results."""
        print(f"\n{'='*80}")
        print(f"Query: {description}")
        print(f"{'='*80}")
        print(f"SQL:\n{query}\n")

        # Start query execution
        response = self.client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={'Database': self.database},
            ResultConfiguration={'OutputLocation': self.output_location}
        )

        query_id = response['QueryExecutionId']
        print(f"Query ID: {query_id}")

        # Wait for query to complete
        while True:
            result = self.client.get_query_execution(QueryExecutionId=query_id)
            state = result['QueryExecution']['Status']['State']

            if state in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
                break

            time.sleep(1)

        if state != 'SUCCEEDED':
            reason = result['QueryExecution']['Status'].get('StateChangeReason', 'Unknown')
            print(f"Query failed: {reason}")
            return None

        # Get results
        results = self.client.get_query_results(QueryExecutionId=query_id, MaxResults=100)
        return self._format_results(results)

    def _format_results(self, results):
        """Format Athena results into readable table."""
        rows = results['ResultSet']['Rows']
        if not rows:
            return "No results"

        # Extract headers
        headers = [col['VarCharValue'] for col in rows[0]['Data']]

        # Extract data rows
        data_rows = []
        for row in rows[1:]:
            data_rows.append([col.get('VarCharValue', '') for col in row['Data']])

        # Calculate column widths
        col_widths = [len(h) for h in headers]
        for row in data_rows:
            for i, val in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(val)))

        # Format output
        output = []
        header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
        output.append(header_line)
        output.append("-" * len(header_line))

        for row in data_rows:
            output.append(" | ".join(str(v).ljust(w) for v, w in zip(row, col_widths)))

        return "\n".join(output)


def get_date_range(days_back=7):
    """Get date range for queries."""
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days_back)
    return start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')


def main():
    runner = AthenaQueryRunner(AWS_REGION, DATABASE, OUTPUT_LOCATION)
    start_date, end_date = get_date_range(7)

    print(f"\nAnalyzing CUR 2.0 data from {start_date} to {end_date}")
    print(f"Cluster: {CLUSTER_NAME}")

    # Query 1: Total EKS Cost by Day
    query1 = f"""
    SELECT
        DATE(line_item_usage_start_date) as usage_date,
        COUNT(DISTINCT line_item_resource_id) as pod_count,
        ROUND(SUM(line_item_unblended_cost), 4) as total_cost,
        ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%vCPU%' THEN line_item_unblended_cost ELSE 0 END), 4) as vcpu_cost,
        ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%GB%' THEN line_item_unblended_cost ELSE 0 END), 4) as memory_cost
    FROM {TABLE}
    WHERE line_item_product_code = 'AmazonEKS'
        AND line_item_resource_id LIKE 'arn:aws:eks:{AWS_REGION}:%:pod/{CLUSTER_NAME}/%'
        AND DATE(line_item_usage_start_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    GROUP BY DATE(line_item_usage_start_date)
    ORDER BY usage_date DESC
    """
    results = runner.execute_query(query1, "Total EKS Cost by Day (vCPU + Memory)")
    if results:
        print(results)

    # Query 2: Cost by Namespace
    query2 = f"""
    WITH pod_info AS (
        SELECT
            line_item_resource_id,
            SPLIT_PART(SPLIT_PART(line_item_resource_id, '/pod/{CLUSTER_NAME}/', 2), '/', 1) as namespace,
            SPLIT_PART(SPLIT_PART(line_item_resource_id, '/pod/{CLUSTER_NAME}/', 2), '/', 2) as pod_name,
            line_item_unblended_cost,
            line_item_usage_type
        FROM {TABLE}
        WHERE line_item_product_code = 'AmazonEKS'
            AND line_item_resource_id LIKE 'arn:aws:eks:{AWS_REGION}:%:pod/{CLUSTER_NAME}/%'
            AND DATE(line_item_usage_start_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    )
    SELECT
        namespace,
        COUNT(DISTINCT pod_name) as unique_pods,
        ROUND(SUM(line_item_unblended_cost), 4) as total_cost,
        ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%vCPU%' THEN line_item_unblended_cost ELSE 0 END), 4) as vcpu_cost,
        ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%GB%' THEN line_item_unblended_cost ELSE 0 END), 4) as memory_cost
    FROM pod_info
    GROUP BY namespace
    ORDER BY total_cost DESC
    """
    results = runner.execute_query(query2, "Cost by Namespace")
    if results:
        print(results)

    # Query 3: Top 10 Most Expensive Pods
    query3 = f"""
    WITH pod_costs AS (
        SELECT
            SPLIT_PART(SPLIT_PART(line_item_resource_id, '/pod/{CLUSTER_NAME}/', 2), '/', 1) as namespace,
            SPLIT_PART(SPLIT_PART(line_item_resource_id, '/pod/{CLUSTER_NAME}/', 2), '/', 2) as pod_name,
            line_item_unblended_cost,
            line_item_usage_type,
            split_line_item_split_usage as split_usage
        FROM {TABLE}
        WHERE line_item_product_code = 'AmazonEKS'
            AND line_item_resource_id LIKE 'arn:aws:eks:{AWS_REGION}:%:pod/{CLUSTER_NAME}/%'
            AND DATE(line_item_usage_start_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    )
    SELECT
        namespace,
        pod_name,
        ROUND(SUM(line_item_unblended_cost), 6) as total_cost,
        ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%vCPU%' THEN line_item_unblended_cost ELSE 0 END), 6) as vcpu_cost,
        ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%GB%' THEN line_item_unblended_cost ELSE 0 END), 6) as memory_cost,
        ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%vCPU%' THEN split_usage ELSE 0 END), 4) as vcpu_hours,
        ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%GB%' THEN split_usage ELSE 0 END), 4) as gb_hours
    FROM pod_costs
    GROUP BY namespace, pod_name
    ORDER BY total_cost DESC
    LIMIT 10
    """
    results = runner.execute_query(query3, "Top 10 Most Expensive Pods")
    if results:
        print(results)

    # Query 4: Resource Usage Summary (vCPU and Memory hours)
    query4 = f"""
    SELECT
        line_item_usage_type as resource_type,
        COUNT(*) as line_items,
        ROUND(SUM(split_line_item_split_usage), 2) as total_usage,
        ROUND(SUM(line_item_unblended_cost), 4) as total_cost,
        ROUND(AVG(line_item_unblended_rate), 6) as avg_rate_per_unit
    FROM {TABLE}
    WHERE line_item_product_code = 'AmazonEKS'
        AND line_item_resource_id LIKE 'arn:aws:eks:{AWS_REGION}:%:pod/{CLUSTER_NAME}/%'
        AND DATE(line_item_usage_start_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    GROUP BY line_item_usage_type
    ORDER BY total_cost DESC
    """
    results = runner.execute_query(query4, "Resource Usage Summary")
    if results:
        print(results)

    # Query 5: Cost by Availability Zone
    query5 = f"""
    SELECT
        line_item_availability_zone as az,
        ROUND(SUM(line_item_unblended_cost), 4) as total_cost,
        ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%vCPU%' THEN line_item_unblended_cost ELSE 0 END), 4) as vcpu_cost,
        ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%GB%' THEN line_item_unblended_cost ELSE 0 END), 4) as memory_cost,
        COUNT(DISTINCT line_item_resource_id) as pod_count
    FROM {TABLE}
    WHERE line_item_product_code = 'AmazonEKS'
        AND line_item_resource_id LIKE 'arn:aws:eks:{AWS_REGION}:%:pod/{CLUSTER_NAME}/%'
        AND DATE(line_item_usage_start_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    GROUP BY line_item_availability_zone
    ORDER BY total_cost DESC
    """
    results = runner.execute_query(query5, "Cost by Availability Zone")
    if results:
        print(results)

    # Query 6: Hourly Cost Trend (Last 24 hours)
    query6 = f"""
    SELECT
        DATE_FORMAT(line_item_usage_start_date, '%Y-%m-%d %H:00') as hour,
        COUNT(DISTINCT line_item_resource_id) as active_pods,
        ROUND(SUM(line_item_unblended_cost), 6) as hourly_cost
    FROM {TABLE}
    WHERE line_item_product_code = 'AmazonEKS'
        AND line_item_resource_id LIKE 'arn:aws:eks:{AWS_REGION}:%:pod/{CLUSTER_NAME}/%'
        AND line_item_usage_start_date >= CURRENT_TIMESTAMP - INTERVAL '24' HOUR
    GROUP BY DATE_FORMAT(line_item_usage_start_date, '%Y-%m-%d %H:00')
    ORDER BY hour DESC
    LIMIT 24
    """
    results = runner.execute_query(query6, "Hourly Cost Trend (Last 24 hours)")
    if results:
        print(results)

    # Query 7: Pod Lifetime Analysis
    query7 = f"""
    WITH pod_times AS (
        SELECT
            SPLIT_PART(SPLIT_PART(line_item_resource_id, '/pod/{CLUSTER_NAME}/', 2), '/', 1) as namespace,
            SPLIT_PART(SPLIT_PART(line_item_resource_id, '/pod/{CLUSTER_NAME}/', 2), '/', 2) as pod_name,
            MIN(line_item_usage_start_date) as first_seen,
            MAX(line_item_usage_end_date) as last_seen,
            SUM(line_item_unblended_cost) as total_cost
        FROM {TABLE}
        WHERE line_item_product_code = 'AmazonEKS'
            AND line_item_resource_id LIKE 'arn:aws:eks:{AWS_REGION}:%:pod/{CLUSTER_NAME}/%'
            AND DATE(line_item_usage_start_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
        GROUP BY
            SPLIT_PART(SPLIT_PART(line_item_resource_id, '/pod/{CLUSTER_NAME}/', 2), '/', 1),
            SPLIT_PART(SPLIT_PART(line_item_resource_id, '/pod/{CLUSTER_NAME}/', 2), '/', 2)
    )
    SELECT
        namespace,
        pod_name,
        first_seen,
        last_seen,
        DATE_DIFF('hour', first_seen, last_seen) as lifetime_hours,
        ROUND(total_cost, 6) as total_cost,
        ROUND(total_cost / GREATEST(DATE_DIFF('hour', first_seen, last_seen), 1), 6) as cost_per_hour
    FROM pod_times
    ORDER BY total_cost DESC
    LIMIT 15
    """
    results = runner.execute_query(query7, "Pod Lifetime and Cost Analysis")
    if results:
        print(results)

    # Query 8: Split Line Item Details (Shows actual vs allocated usage)
    query8 = f"""
    SELECT
        SPLIT_PART(SPLIT_PART(line_item_resource_id, '/pod/{CLUSTER_NAME}/', 2), '/', 1) as namespace,
        SPLIT_PART(SPLIT_PART(line_item_resource_id, '/pod/{CLUSTER_NAME}/', 2), '/', 2) as pod_name,
        line_item_usage_type,
        ROUND(SUM(split_line_item_actual_usage), 4) as actual_usage,
        ROUND(SUM(split_line_item_split_usage), 4) as allocated_usage,
        ROUND(SUM(split_line_item_split_usage_ratio), 4) as allocation_ratio,
        ROUND(SUM(split_line_item_split_cost), 6) as allocated_cost
    FROM {TABLE}
    WHERE line_item_product_code = 'AmazonEKS'
        AND line_item_resource_id LIKE 'arn:aws:eks:{AWS_REGION}:%:pod/{CLUSTER_NAME}/%'
        AND DATE(line_item_usage_start_date) = CURRENT_DATE - INTERVAL '1' DAY
    GROUP BY
        SPLIT_PART(SPLIT_PART(line_item_resource_id, '/pod/{CLUSTER_NAME}/', 2), '/', 1),
        SPLIT_PART(SPLIT_PART(line_item_resource_id, '/pod/{CLUSTER_NAME}/', 2), '/', 2),
        line_item_usage_type
    ORDER BY allocated_cost DESC
    LIMIT 20
    """
    results = runner.execute_query(query8, "Split Line Item Details (Yesterday)")
    if results:
        print(results)

    print(f"\n{'='*80}")
    print("Analysis Complete!")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
