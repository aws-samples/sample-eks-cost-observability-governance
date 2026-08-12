# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#!/usr/bin/env python3
"""
CUR 2.0 Data Explorer Script

This script analyzes your AWS Cost and Usage Report (CUR 2.0) data in Athena
to understand the schema and tag structure for EKS cost collection.

Usage:
    python explore_cur_data.py --profile brdcost --database billingdata --table data
"""

import argparse
from datetime import datetime, timedelta

import awswrangler as wr
import boto3
import pandas as pd


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


def explore_eks_data(session, database, table, s3_output, cluster_name, lookback_days):
    """Explore EKS cost data in CUR."""

    # Calculate date range
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=lookback_days)

    print(f"📅 Date Range: {start_date} to {end_date} ({lookback_days} days)")
    print(f"🏢 Database: {database}.{table}")
    print(f"☸️  Cluster: {cluster_name}")
    print(f"📦 S3 Output: {s3_output}")

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

    try:
        df1 = wr.athena.read_sql_query(
            sql=query1,
            database=database,
            boto3_session=session,
            ctas_approach=False,
            s3_output=s3_output
        )

        if not df1.empty and df1['record_count'].iloc[0] > 0:
            print("✅ EKS data found!")
            print(f"   Records: {df1['record_count'].iloc[0]:,}")
            print(f"   Unique Resources: {df1['unique_resources'].iloc[0]:,}")
            print(f"   Date Range: {df1['earliest_date'].iloc[0]} to {df1['latest_date'].iloc[0]}")
            print(f"   Total Cost: ${df1['total_cost'].iloc[0]:,.2f}")
        else:
            print("❌ No EKS data found in this date range")
            print("   Try increasing --days parameter")
            return
    except Exception as e:
        print(f"❌ Error querying EKS data: {e}")
        return

    # =========================================================================
    # Query 2: Total Cost by Cluster
    # =========================================================================
    print_section("2. Total Cost by Cluster")

    query2 = f"""
    SELECT
        CASE
            WHEN line_item_resource_id LIKE '%cluster/%' AND line_item_resource_id LIKE '%pod/%' THEN
                SPLIT_PART(SPLIT_PART(line_item_resource_id, '/cluster/', 2), '/', 1)
            WHEN line_item_resource_id LIKE '%cluster/%' THEN
                SPLIT_PART(SPLIT_PART(line_item_resource_id, '/cluster/', 2), '/', 1)
            ELSE 'unknown'
        END as cluster_name,
        CASE
            WHEN line_item_resource_id LIKE '%pod/%' THEN 'pod'
            ELSE 'cluster'
        END as resource_type,
        COUNT(*) as line_items,
        SUM(line_item_unblended_cost) as unblended_cost,
        SUM(split_line_item_split_cost) as split_cost,
        COUNT(DISTINCT line_item_resource_id) as unique_resources
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND line_item_usage_start_date >= DATE('{start_date}')
        AND line_item_usage_start_date < DATE('{end_date}')
    GROUP BY 1, 2
    ORDER BY split_cost DESC
    """

    try:
        df2 = wr.athena.read_sql_query(
            sql=query2,
            database=database,
            boto3_session=session,
            ctas_approach=False,
            s3_output=s3_output
        )

        if not df2.empty:
            print("✅ EKS Cost Breakdown by Cluster:\n")

            # Group by cluster
            for cluster in df2['cluster_name'].unique():
                cluster_data = df2[df2['cluster_name'] == cluster]
                total_cost = cluster_data['split_cost'].sum()
                pod_cost = cluster_data[cluster_data['resource_type'] == 'pod']['split_cost'].sum()
                cluster_cost = cluster_data[cluster_data['resource_type'] == 'cluster']['split_cost'].sum()

                print(f"   📊 Cluster: {cluster}")
                print(f"      Total Cost: ${total_cost:,.2f}")
                print(f"      - Pod Cost: ${pod_cost:,.2f} ({pod_cost/total_cost*100:.1f}%)" if total_cost > 0 else "      - Pod Cost: $0.00")
                print(f"      - Cluster Cost: ${cluster_cost:,.2f} ({cluster_cost/total_cost*100:.1f}%)" if total_cost > 0 else "      - Cluster Cost: $0.00")
                print(f"      - Unique Resources: {cluster_data['unique_resources'].sum():,}")
                print()
        else:
            print("❌ No cluster cost data found")
    except Exception as e:
        print(f"❌ Error querying cluster costs: {e}")

    # =========================================================================
    # Query 3: Check for Split-Cost Allocation Data
    # =========================================================================
    print_section("3. Checking for Split-Cost Allocation")

    query3 = f"""
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

    try:
        df3 = wr.athena.read_sql_query(
            sql=query3,
            database=database,
            boto3_session=session,
            ctas_approach=False,
            s3_output=s3_output
        )

        total = df3['total_records'].iloc[0]
        split = df3['split_cost_records'].iloc[0]
        split_pct = (split / total * 100) if total > 0 else 0

        if split > 0:
            print("✅ Split-cost allocation is enabled!")
            print(f"   Total Records: {total:,}")
            print(f"   Split-Cost Records: {split:,} ({split_pct:.1f}%)")
            print(f"   Split-Cost Total: ${df3['split_cost_total'].iloc[0]:,.2f}")
            print(f"   Unblended Cost Total: ${df3['unblended_cost_total'].iloc[0]:,.2f}")
        else:
            print("⚠️  Split-cost allocation may not be enabled")
            print(f"   Found {total:,} EKS records but no split-cost data")
            print("   Check: https://docs.aws.amazon.com/eks/latest/userguide/split-cost-allocation.html")
    except Exception as e:
        print(f"❌ Error checking split-cost data: {e}")

    # =========================================================================
    # Query 4: Analyze Resource IDs (Find Pods)
    # =========================================================================
    print_section("4. Analyzing Resource IDs")

    query4 = f"""
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

    try:
        df4 = wr.athena.read_sql_query(
            sql=query4,
            database=database,
            boto3_session=session,
            ctas_approach=False,
            s3_output=s3_output
        )

        if not df4.empty:
            print(f"✅ Found {len(df4)} sample resources")
            print("\nResource ID Patterns:")

            # Categorize resource IDs
            cluster_count = 0
            pod_count = 0
            other_count = 0

            for rid in df4['line_item_resource_id']:
                if 'cluster/' in str(rid):
                    if 'pod/' in str(rid):
                        pod_count += 1
                        if pod_count <= 3:  # Show first 3 pod examples
                            print(f"   🔸 Pod: {rid}")
                    else:
                        cluster_count += 1
                        if cluster_count == 1:
                            print(f"   🔸 Cluster: {rid}")
                else:
                    other_count += 1

            print(f"\n   Total: {len(df4)} resources")
            print(f"   - Pods: {pod_count}")
            print(f"   - Clusters: {cluster_count}")
            print(f"   - Other: {other_count}")

            # Check if cluster name appears in resource IDs
            cluster_in_data = df4['line_item_resource_id'].str.contains(cluster_name, na=False).sum()
            if cluster_in_data > 0:
                print(f"\n   ✅ Cluster '{cluster_name}' found in {cluster_in_data} resource IDs")
            else:
                print(f"\n   ⚠️  Cluster '{cluster_name}' NOT found in resource IDs")
                print("      Check --cluster parameter or your cluster name")
        else:
            print("❌ No resource IDs found with split costs")
    except Exception as e:
        print(f"❌ Error analyzing resource IDs: {e}")

    # =========================================================================
    # Query 5: Explore Tag Structure (THE MOST IMPORTANT PART!)
    # =========================================================================
    print_section("5. Exploring Tag Structure")

    query5 = f"""
    SELECT
        line_item_resource_id,
        resource_tags,
        tags,
        split_line_item_split_cost
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND split_line_item_split_cost > 0
        AND line_item_resource_id LIKE '%pod%'
        AND line_item_usage_start_date >= DATE('{start_date}')
        AND line_item_usage_start_date < DATE('{end_date}')
    LIMIT 10
    """

    try:
        df5 = wr.athena.read_sql_query(
            sql=query5,
            database=database,
            boto3_session=session,
            ctas_approach=False,
            s3_output=s3_output
        )

        if not df5.empty:
            print(f"✅ Found {len(df5)} pod records with tags")

            # Analyze resource_tags
            print("\n📋 Analyzing 'resource_tags' column:")
            has_resource_tags = False
            all_tag_keys = set()

            for idx, row in df5.iterrows():
                if pd.notna(row['resource_tags']) and row['resource_tags']:
                    has_resource_tags = True
                    tags = row['resource_tags']

                    # Tags are returned as dict from awswrangler
                    if isinstance(tags, dict):
                        tag_keys = list(tags.keys())
                        all_tag_keys.update(tag_keys)

                        print(f"\n   Pod {idx + 1}: {row['line_item_resource_id'][-50:]}")
                        print(f"   Cost: ${row['split_line_item_split_cost']:.4f}")
                        print(f"   Tags ({len(tags)}):")
                        for key, value in list(tags.items())[:10]:  # Show first 10 tags
                            print(f"      - {key}: {value}")
                        if len(tags) > 10:
                            print(f"      ... and {len(tags) - 10} more tags")

            if has_resource_tags:
                print("\n   ✅ resource_tags column has data!")
                print(f"   📊 Unique tag keys found: {len(all_tag_keys)}")

                # Look for cost governance tags
                cost_tags = [
                    'cost-center', 'business-unit', 'team', 'application', 'environment',
                    'user:cost-center', 'user:business-unit', 'user:team',
                    'aws:eks:cost-center', 'aws:eks:business-unit', 'aws:eks:team'
                ]

                found_cost_tags = [tag for tag in cost_tags if tag in all_tag_keys]

                if found_cost_tags:
                    print("\n   ✅ Cost governance tags found:")
                    for tag in found_cost_tags:
                        print(f"      - {tag}")
                else:
                    print("\n   ⚠️  No standard cost governance tags found")
                    print("   Available tag keys (first 20):")
                    for tag in list(all_tag_keys)[:20]:
                        print(f"      - {tag}")
            else:
                print("   ❌ resource_tags column is empty")

            # Analyze tags column
            print("\n📋 Analyzing 'tags' column:")
            has_tags = False

            for idx, row in df5.iterrows():
                if pd.notna(row['tags']) and row['tags']:
                    has_tags = True
                    if isinstance(row['tags'], dict) and idx == 0:  # Show first example
                        print(f"   Tags found: {list(row['tags'].keys())[:10]}")
                    break

            if not has_tags:
                print("   ℹ️  'tags' column is empty (this is normal)")
        else:
            print("❌ No pod records found with split costs")
            print("   This might mean:")
            print("   - Split-cost allocation is not enabled on your cluster")
            print("   - No pods have run in the date range")
            print("   - Pods exist but have zero cost")
    except Exception as e:
        print(f"❌ Error exploring tags: {e}")

    # =========================================================================
    # Query 6: Test Tag Extraction (Multiple Formats)
    # =========================================================================
    print_section("6. Testing Tag Extraction Methods")

    # Try different tag key formats
    tag_formats = [
        "'cost-center'",
        "'user:cost-center'",
        "'aws:eks:cost-center'",
        "'team'",
        "'user:team'",
        "'aws:eks:team'",
        "'business-unit'",
        "'user:business-unit'",
    ]

    tag_selects = []
    for i, tag in enumerate(tag_formats):
        tag_selects.append(f"resource_tags[{tag}] as tag_format_{i+1}")

    query6 = f"""
    SELECT
        line_item_resource_id,
        {', '.join(tag_selects)},
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

    try:
        df6 = wr.athena.read_sql_query(
            sql=query6,
            database=database,
            boto3_session=session,
            ctas_approach=False,
            s3_output=s3_output
        )

        if not df6.empty:
            print("Testing different tag key formats:")
            print("\nFormat tested:")
            for i, tag in enumerate(tag_formats):
                print(f"   {i+1}. resource_tags[{tag}]")

            print("\nResults:")
            for col_idx, col in enumerate([c for c in df6.columns if c.startswith('tag_format_')]):
                non_null = df6[col].notna().sum()
                if non_null > 0:
                    print(f"   ✅ Format {col_idx + 1} works! ({non_null}/{len(df6)} records have values)")
                    print(f"      resource_tags[{tag_formats[col_idx]}]")
                    print(f"      Sample values: {df6[col].dropna().unique()[:3].tolist()}")
                else:
                    print(f"   ❌ Format {col_idx + 1} - No data")
        else:
            print("❌ No data returned for tag extraction test")
    except Exception as e:
        print(f"❌ Error testing tag extraction: {e}")

    # =========================================================================
    # Summary and Recommendations
    # =========================================================================
    print_section("7. Summary and Recommendations")

    print("📝 What to do next:\n")
    print("1. ✅ Review the cluster cost breakdown in Section 2")
    print("2. ✅ Review the tag structure findings in Section 5")
    print("3. 📋 Note which tag key format works (from Section 6)")
    print("4. 🔧 Update the collector code to use the correct tag keys")
    print("5. 🚀 Ready to implement Phase 3!\n")

    print("📊 Configuration to use:")
    print(f"   Database: {database}")
    print(f"   Table: {table}")
    print(f"   Cluster: {cluster_name}")
    print(f"   S3 Output: {s3_output}")
    print("   Cost Column: split_line_item_split_cost")
    print("   Tag Column: resource_tags (map)")


def main():
    """Main execution."""
    args = setup_args()

    print("\n" + "🔍" * 40)
    print("  CUR 2.0 Data Explorer")
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
        print(f"   Check that profile '{args.profile}' exists in ~/.aws/credentials")
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
