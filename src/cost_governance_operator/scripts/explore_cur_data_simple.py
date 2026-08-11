#!/usr/bin/env python3
"""
CUR 2.0 Data Explorer Script (boto3-only version)

This script analyzes your AWS Cost and Usage Report (CUR 2.0) data in Athena
to understand the schema and tag structure for EKS cost collection.

Usage:
    python explore_cur_data_simple.py --profile brdcost --database billingdata --table data
"""

import argparse
import time
from datetime import datetime, timedelta

import boto3


def setup_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Explore CUR 2.0 data structure')
    parser.add_argument(
        '--profile',
        default='brdcost',
        help='AWS profile name (default: brdcost)'
    )
    parser.add_argument(
        '--database',
        default='billingdata',
        help='Athena database name (default: billingdata)'
    )
    parser.add_argument(
        '--table',
        default='data',
        help='CUR table name (default: data)'
    )
    parser.add_argument(
        '--cluster',
        default='cost-demo-eks-cluster',
        help='EKS cluster name (default: cost-demo-eks-cluster)'
    )
    parser.add_argument(
        '--s3-output',
        default='s3://athena-results-783837106602-us-east-1-an/',
        help='S3 location for Athena query results'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=30,
        help='Look back this many days (default: 30)'
    )
    parser.add_argument(
        '--region',
        default='us-east-1',
        help='AWS region (default: us-east-1)'
    )
    return parser.parse_args()


def print_section(title):
    """Print a section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def execute_athena_query(athena_client, query, database, s3_output):
    """
    Execute Athena query and wait for results.

    Returns:
        query_execution_id if successful, None otherwise
    """
    try:
        # Start query execution
        response = athena_client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={'Database': database},
            ResultConfiguration={'OutputLocation': s3_output}
        )

        query_execution_id = response['QueryExecutionId']

        # Wait for query to complete
        max_wait = 60  # seconds
        wait_interval = 2  # seconds
        elapsed = 0

        while elapsed < max_wait:
            response = athena_client.get_query_execution(
                QueryExecutionId=query_execution_id
            )

            status = response['QueryExecution']['Status']['State']

            if status == 'SUCCEEDED':
                return query_execution_id
            elif status in ['FAILED', 'CANCELLED']:
                reason = response['QueryExecution']['Status'].get('StateChangeReason', 'Unknown')
                print(f"   ❌ Query failed: {reason}")
                return None

            time.sleep(wait_interval)
            elapsed += wait_interval

        print(f"   ⚠️  Query timed out after {max_wait} seconds")
        return None

    except Exception as e:
        print(f"   ❌ Error executing query: {e}")
        return None


def get_query_results(athena_client, query_execution_id):
    """
    Get query results.

    Returns:
        List of rows (each row is a dict)
    """
    try:
        # Get results
        paginator = athena_client.get_paginator('get_query_results')
        page_iterator = paginator.paginate(QueryExecutionId=query_execution_id)

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
                    row_data[col_name] = col.get('VarCharValue', None)
                results.append(row_data)

        return results

    except Exception as e:
        print(f"   ❌ Error getting query results: {e}")
        return []


def explore_eks_data(session, database, table, s3_output, cluster_name, lookback_days):
    """Explore EKS cost data in CUR."""

    # Calculate date range
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=lookback_days)

    print(f"📅 Date Range: {start_date} to {end_date} ({lookback_days} days)")
    print(f"🏢 Database: {database}.{table}")
    print(f"☸️  Cluster: {cluster_name}")
    print(f"📦 S3 Output: {s3_output}")

    # Create Athena client
    athena_client = session.client('athena')

    # =========================================================================
    # Query 1: Check if EKS data exists
    # =========================================================================
    print_section("1. Checking for EKS Data")

    query1 = f"""
    SELECT
        COUNT(*) as record_count,
        COUNT(DISTINCT line_item_resource_id) as unique_resources,
        MIN(line_item_usage_start_date) as earliest_date,
        MAX(line_item_usage_start_date) as latest_date,
        SUM(split_line_item_split_cost) as total_cost
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND line_item_usage_start_date >= DATE('{start_date}')
        AND line_item_usage_start_date < DATE('{end_date}')
    """

    print("Executing query...")
    query_id = execute_athena_query(athena_client, query1, database, s3_output)

    if not query_id:
        print("Failed to execute query")
        return

    results = get_query_results(athena_client, query_id)

    if results and results[0].get('record_count') and int(results[0]['record_count']) > 0:
        print("✅ EKS data found!")
        print(f"   Records: {int(results[0]['record_count']):,}")
        print(f"   Unique Resources: {int(results[0]['unique_resources']):,}")
        print(f"   Date Range: {results[0]['earliest_date']} to {results[0]['latest_date']}")
        total_cost = float(results[0]['total_cost']) if results[0]['total_cost'] else 0
        print(f"   Total Cost: ${total_cost:,.2f}")
    else:
        print("❌ No EKS data found in this date range")
        print("   Try increasing --days parameter")
        return

    # =========================================================================
    # Query 2: Check for Split-Cost Allocation Data
    # =========================================================================
    print_section("2. Checking for Split-Cost Allocation")

    query2 = f"""
    SELECT
        COUNT(*) as total_records,
        COUNT(CASE WHEN split_line_item_split_cost IS NOT NULL AND split_line_item_split_cost > 0 THEN 1 END) as split_cost_records,
        SUM(CASE WHEN split_line_item_split_cost IS NOT NULL THEN split_line_item_split_cost ELSE 0 END) as split_cost_total,
        SUM(line_item_unblended_cost) as unblended_cost_total
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND line_item_usage_start_date >= DATE('{start_date}')
        AND line_item_usage_start_date < DATE('{end_date}')
    """

    print("Executing query...")
    query_id = execute_athena_query(athena_client, query2, database, s3_output)

    if query_id:
        results = get_query_results(athena_client, query_id)

        if results:
            total = int(results[0]['total_records'])
            split = int(results[0]['split_cost_records'])
            split_pct = (split / total * 100) if total > 0 else 0

            if split > 0:
                print("✅ Split-cost allocation is enabled!")
                print(f"   Total Records: {total:,}")
                print(f"   Split-Cost Records: {split:,} ({split_pct:.1f}%)")
                split_total = float(results[0]['split_cost_total']) if results[0]['split_cost_total'] else 0
                unblended_total = float(results[0]['unblended_cost_total']) if results[0]['unblended_cost_total'] else 0
                print(f"   Split-Cost Total: ${split_total:,.2f}")
                print(f"   Unblended Cost Total: ${unblended_total:,.2f}")
            else:
                print("⚠️  Split-cost allocation may not be enabled")
                print(f"   Found {total:,} EKS records but no split-cost data")

    # =========================================================================
    # Query 3: Analyze Resource IDs (Find Pods)
    # =========================================================================
    print_section("3. Analyzing Resource IDs")

    query3 = f"""
    SELECT
        line_item_resource_id,
        split_line_item_split_cost
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND split_line_item_split_cost > 0
        AND line_item_usage_start_date >= DATE('{start_date}')
        AND line_item_usage_start_date < DATE('{end_date}')
    LIMIT 20
    """

    print("Executing query...")
    query_id = execute_athena_query(athena_client, query3, database, s3_output)

    if query_id:
        results = get_query_results(athena_client, query_id)

        if results:
            print(f"✅ Found {len(results)} sample resources")
            print("\nResource ID Patterns:")

            # Categorize resource IDs
            cluster_count = 0
            pod_count = 0
            cluster_in_name = 0

            for row in results:
                rid = row['line_item_resource_id']

                if 'cluster/' in rid:
                    if 'pod/' in rid:
                        pod_count += 1
                        if pod_count <= 3:  # Show first 3 pod examples
                            print(f"   🔸 Pod: {rid}")
                    else:
                        cluster_count += 1
                        if cluster_count == 1:
                            print(f"   🔸 Cluster: {rid}")

                if cluster_name in rid:
                    cluster_in_name += 1

            print(f"\n   Total: {len(results)} resources")
            print(f"   - Pods: {pod_count}")
            print(f"   - Clusters: {cluster_count}")

            if cluster_in_name > 0:
                print(f"\n   ✅ Cluster '{cluster_name}' found in {cluster_in_name} resource IDs")
            else:
                print(f"\n   ⚠️  Cluster '{cluster_name}' NOT found in resource IDs")

    # =========================================================================
    # Query 4: Explore Tag Structure (THE MOST IMPORTANT PART!)
    # =========================================================================
    print_section("4. Exploring Tag Structure")

    query4 = f"""
    SELECT
        line_item_resource_id,
        resource_tags,
        split_line_item_split_cost
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND split_line_item_split_cost > 0
        AND line_item_resource_id LIKE '%pod%'
        AND line_item_usage_start_date >= DATE('{start_date}')
        AND line_item_usage_start_date < DATE('{end_date}')
    LIMIT 5
    """

    print("Executing query...")
    query_id = execute_athena_query(athena_client, query4, database, s3_output)

    if query_id:
        results = get_query_results(athena_client, query_id)

        if results:
            print(f"✅ Found {len(results)} pod records")
            print("\n📋 Resource Tags Structure:")

            all_tag_keys = set()

            for idx, row in enumerate(results, 1):
                rid = row['line_item_resource_id']
                tags_str = row.get('resource_tags', '')
                cost = row.get('split_line_item_split_cost', '0')

                print(f"\n   Pod {idx}: ...{rid[-60:]}")
                print(f"   Cost: ${float(cost):.4f}")

                if tags_str and tags_str != 'null':
                    # Parse tag map (format: {key1=value1, key2=value2})
                    print(f"   Raw tags: {tags_str[:200]}")

                    # Try to extract tag keys
                    if '=' in tags_str:
                        # Simple parsing - look for patterns like "key=value"
                        pairs = tags_str.replace('{', '').replace('}', '').split(',')
                        for pair in pairs[:10]:  # First 10
                            if '=' in pair:
                                key = pair.split('=')[0].strip()
                                all_tag_keys.add(key)
                                print(f"      - {pair.strip()}")
                else:
                    print("   ⚠️  No tags found")

            if all_tag_keys:
                print(f"\n   📊 Unique tag keys found: {len(all_tag_keys)}")
                print(f"   Tag keys: {list(all_tag_keys)[:20]}")

                # Look for cost governance tags
                cost_tags = ['cost-center', 'business-unit', 'team', 'application', 'environment']
                found_cost_tags = [tag for tag in cost_tags if any(tag in key for key in all_tag_keys)]

                if found_cost_tags:
                    print(f"\n   ✅ Cost governance tags found: {found_cost_tags}")
                else:
                    print("\n   ⚠️  No standard cost governance tags found")
        else:
            print("❌ No pod records found")

    # =========================================================================
    # Query 5: Test Tag Extraction
    # =========================================================================
    print_section("5. Testing Tag Extraction Methods")

    # Try different tag key formats
    tag_tests = [
        ("resource_tags['cost-center']", "cost-center"),
        ("resource_tags['user:cost-center']", "user:cost-center"),
        ("resource_tags['team']", "team"),
        ("resource_tags['user:team']", "user:team"),
        ("resource_tags['business-unit']", "business-unit"),
    ]

    for sql_expr, tag_name in tag_tests:
        query5 = f"""
        SELECT
            line_item_resource_id,
            {sql_expr} as tag_value,
            split_line_item_split_cost
        FROM {database}.{table}
        WHERE
            line_item_product_code = 'AmazonEKS'
            AND split_line_item_split_cost > 0
            AND line_item_resource_id LIKE '%pod%'
            AND {sql_expr} IS NOT NULL
            AND line_item_usage_start_date >= DATE('{start_date}')
            AND line_item_usage_start_date < DATE('{end_date}')
        LIMIT 3
        """

        print(f"\nTesting: {sql_expr}")
        query_id = execute_athena_query(athena_client, query5, database, s3_output)

        if query_id:
            results = get_query_results(athena_client, query_id)

            if results:
                print(f"   ✅ Format works! Found {len(results)} records")
                sample_values = [r['tag_value'] for r in results[:3] if r.get('tag_value')]
                print(f"   Sample values: {sample_values}")
            else:
                print("   ❌ No data with this format")

    # =========================================================================
    # Summary
    # =========================================================================
    print_section("6. Summary")

    print("📝 Configuration to use:")
    print(f"   Database: {database}")
    print(f"   Table: {table}")
    print(f"   Cluster: {cluster_name}")
    print(f"   S3 Output: {s3_output}")
    print("   Cost Column: split_line_item_split_cost")
    print("   Tag Column: resource_tags")
    print("\n✅ Review the tag extraction results above to determine the correct tag key format!")


def main():
    """Main execution."""
    args = setup_args()

    print("\n" + "🔍" * 40)
    print("  CUR 2.0 Data Explorer (boto3-only)")
    print("🔍" * 40 + "\n")

    # Create boto3 session with profile
    try:
        session = boto3.Session(
            profile_name=args.profile,
            region_name=args.region
        )
        print(f"✅ Connected to AWS using profile: {args.profile}")
        print(f"   Region: {args.region}")
    except Exception as e:
        print(f"❌ Failed to create AWS session: {e}")
        return 1

    # Run exploration
    try:
        explore_eks_data(
            session=session,
            database=args.database,
            table=args.table,
            s3_output=args.s3_output,
            cluster_name=args.cluster,
            lookback_days=args.days
        )
    except Exception as e:
        print(f"\n❌ Exploration failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n" + "=" * 80)
    print("✅ Exploration complete!")
    print("=" * 80 + "\n")

    return 0


if __name__ == '__main__':
    exit(main())
