#!/usr/bin/env python3
"""
EKS Cost Explorer - Analyze CUR 2.0 EKS costs by various dimensions

This script provides comprehensive cost breakdowns for EKS clusters using
the actual tag structure from CUR 2.0 data.

Usage:
    python explore_eks_costs.py --profile brdcost --database billingdata --table data
"""

import argparse
import boto3
import awswrangler as wr
import pandas as pd
from datetime import datetime, timedelta
from decimal import Decimal


def setup_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Explore EKS costs from CUR 2.0')
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
        default=7,
        help='Look back this many days (default: 7)'
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


def format_cost(amount):
    """Format cost with proper decimal places."""
    if pd.isna(amount) or amount == 0:
        return "$0.00"
    elif amount < 0.01:
        return f"${amount:.4f}"
    elif amount < 1:
        return f"${amount:.3f}"
    else:
        return f"${amount:,.2f}"


def query_1_total_cluster_cost(session, database, table, s3_output, cluster_name, start_date, end_date):
    """Query 1: Total EKS cluster cost."""
    print_section("1. Total EKS Cluster Cost")

    query = f"""
    SELECT
        resource_tags['aws_eks_cluster_name'] as cluster_name,
        COUNT(*) as line_items,
        SUM(COALESCE(split_line_item_split_cost, line_item_unblended_cost)) as total_cost,
        SUM(CASE WHEN line_item_usage_type LIKE '%vCPU%' THEN COALESCE(split_line_item_split_cost, line_item_unblended_cost) ELSE 0 END) as vcpu_cost,
        SUM(CASE WHEN line_item_usage_type LIKE '%GB%' THEN COALESCE(split_line_item_split_cost, line_item_unblended_cost) ELSE 0 END) as memory_cost,
        MIN(line_item_usage_start_date) as earliest_date,
        MAX(line_item_usage_end_date) as latest_date
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND resource_tags['aws_eks_cluster_name'] = '{cluster_name}'
        AND DATE(line_item_usage_start_date) >= DATE('{start_date}')
        AND DATE(line_item_usage_start_date) < DATE('{end_date}')
    GROUP BY resource_tags['aws_eks_cluster_name']
    """

    df = wr.athena.read_sql_query(sql=query, database=database, boto3_session=session, ctas_approach=False, s3_output=s3_output)

    if not df.empty:
        row = df.iloc[0]
        total = row['total_cost']
        vcpu_pct = (row['vcpu_cost'] / total * 100) if total > 0 else 0
        mem_pct = (row['memory_cost'] / total * 100) if total > 0 else 0

        print(f"📊 Cluster: {row['cluster_name']}")
        print(f"   Period: {row['earliest_date']} to {row['latest_date']}")
        print(f"   Total Cost: {format_cost(total)}")
        print(f"   - vCPU Cost: {format_cost(row['vcpu_cost'])} ({vcpu_pct:.1f}%)")
        print(f"   - Memory Cost: {format_cost(row['memory_cost'])} ({mem_pct:.1f}%)")
        print(f"   Line Items: {row['line_items']:,}")
    else:
        print(f"❌ No data found for cluster: {cluster_name}")


def query_2_cost_by_namespace(session, database, table, s3_output, cluster_name, start_date, end_date):
    """Query 2: Cost by EKS namespace."""
    print_section("2. Cost by EKS Namespace")

    query = f"""
    SELECT
        resource_tags['aws_eks_namespace'] as namespace,
        COUNT(*) as line_items,
        SUM(COALESCE(split_line_item_split_cost, line_item_unblended_cost)) as total_cost,
        SUM(CASE WHEN line_item_usage_type LIKE '%vCPU%' THEN COALESCE(split_line_item_split_cost, line_item_unblended_cost) ELSE 0 END) as vcpu_cost,
        SUM(CASE WHEN line_item_usage_type LIKE '%GB%' THEN COALESCE(split_line_item_split_cost, line_item_unblended_cost) ELSE 0 END) as memory_cost,
        COUNT(DISTINCT resource_tags['aws_eks_workload_name']) as unique_workloads
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

    df = wr.athena.read_sql_query(sql=query, database=database, boto3_session=session, ctas_approach=False, s3_output=s3_output)

    if not df.empty:
        total_cost = df['total_cost'].sum()
        print(f"Found {len(df)} namespaces\n")

        for idx, row in df.iterrows():
            pct = (row['total_cost'] / total_cost * 100) if total_cost > 0 else 0
            print(f"📦 {row['namespace']}")
            print(f"   Total: {format_cost(row['total_cost'])} ({pct:.1f}%)")
            print(f"   - vCPU: {format_cost(row['vcpu_cost'])}")
            print(f"   - Memory: {format_cost(row['memory_cost'])}")
            print(f"   Workloads: {row['unique_workloads']}")
            print()
    else:
        print("❌ No namespace data found")


def query_3_cost_by_workload_type(session, database, table, s3_output, cluster_name, start_date, end_date):
    """Query 3: Cost by workload type (ReplicaSet, DaemonSet, StatefulSet, Job)."""
    print_section("3. Cost by Workload Type")

    query = f"""
    SELECT
        resource_tags['aws_eks_workload_type'] as workload_type,
        COUNT(*) as line_items,
        SUM(COALESCE(split_line_item_split_cost, line_item_unblended_cost)) as total_cost,
        COUNT(DISTINCT resource_tags['aws_eks_workload_name']) as unique_workloads
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

    df = wr.athena.read_sql_query(sql=query, database=database, boto3_session=session, ctas_approach=False, s3_output=s3_output)

    if not df.empty:
        total_cost = df['total_cost'].sum()
        print(f"Found {len(df)} workload types\n")

        for idx, row in df.iterrows():
            pct = (row['total_cost'] / total_cost * 100) if total_cost > 0 else 0
            print(f"⚙️  {row['workload_type']}")
            print(f"   Cost: {format_cost(row['total_cost'])} ({pct:.1f}%)")
            print(f"   Unique Workloads: {row['unique_workloads']}")
            print()
    else:
        print("❌ No workload type data found")


def query_4_top_workloads(session, database, table, s3_output, cluster_name, start_date, end_date, limit=20):
    """Query 4: Top N most expensive workloads."""
    print_section(f"4. Top {limit} Most Expensive Workloads")

    query = f"""
    SELECT
        resource_tags['aws_eks_namespace'] as namespace,
        resource_tags['aws_eks_workload_name'] as workload_name,
        resource_tags['aws_eks_workload_type'] as workload_type,
        resource_tags['aws_eks_deployment'] as deployment,
        SUM(COALESCE(split_line_item_split_cost, line_item_unblended_cost)) as total_cost,
        SUM(CASE WHEN line_item_usage_type LIKE '%vCPU%' THEN COALESCE(split_line_item_split_cost, line_item_unblended_cost) ELSE 0 END) as vcpu_cost,
        SUM(CASE WHEN line_item_usage_type LIKE '%GB%' THEN COALESCE(split_line_item_split_cost, line_item_unblended_cost) ELSE 0 END) as memory_cost,
        SUM(CASE WHEN line_item_usage_type LIKE '%vCPU%' THEN COALESCE(split_line_item_split_usage, 0) ELSE 0 END) as vcpu_hours,
        SUM(CASE WHEN line_item_usage_type LIKE '%GB%' THEN COALESCE(split_line_item_split_usage, 0) ELSE 0 END) as gb_hours
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND resource_tags['aws_eks_cluster_name'] = '{cluster_name}'
        AND resource_tags['aws_eks_workload_name'] IS NOT NULL
        AND DATE(line_item_usage_start_date) >= DATE('{start_date}')
        AND DATE(line_item_usage_start_date) < DATE('{end_date}')
    GROUP BY
        resource_tags['aws_eks_namespace'],
        resource_tags['aws_eks_workload_name'],
        resource_tags['aws_eks_workload_type'],
        resource_tags['aws_eks_deployment']
    ORDER BY total_cost DESC
    LIMIT {limit}
    """

    df = wr.athena.read_sql_query(sql=query, database=database, boto3_session=session, ctas_approach=False, s3_output=s3_output)

    if not df.empty:
        for idx, row in df.iterrows():
            deployment = row['deployment'] if pd.notna(row['deployment']) else 'N/A'
            workload_type = row['workload_type'] if pd.notna(row['workload_type']) else 'N/A'
            print(f"{idx + 1}. 📦 {row['namespace']}/{row['workload_name']}")
            print(f"   Type: {workload_type}, Deployment: {deployment}")
            print(f"   Total Cost: {format_cost(row['total_cost'])}")
            print(f"   - vCPU: {format_cost(row['vcpu_cost'])} ({row['vcpu_hours']:.2f} hours)")
            print(f"   - Memory: {format_cost(row['memory_cost'])} ({row['gb_hours']:.2f} GB-hours)")
            print()
    else:
        print("❌ No workload data found")


def query_5_cost_by_business_unit(session, database, table, s3_output, cluster_name, start_date, end_date):
    """Query 5: Cost by business unit (user tags)."""
    print_section("5. Cost by Business Unit")

    query = f"""
    SELECT
        resource_tags['user_business_unit'] as business_unit,
        COUNT(DISTINCT resource_tags['user_application']) as applications,
        COUNT(DISTINCT resource_tags['aws_eks_namespace']) as namespaces,
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

    df = wr.athena.read_sql_query(sql=query, database=database, boto3_session=session, ctas_approach=False, s3_output=s3_output)

    if not df.empty:
        total_cost = df['total_cost'].sum()
        print(f"Found {len(df)} business units\n")

        for idx, row in df.iterrows():
            pct = (row['total_cost'] / total_cost * 100) if total_cost > 0 else 0
            print(f"🏢 {row['business_unit']}")
            print(f"   Cost: {format_cost(row['total_cost'])} ({pct:.1f}%)")
            print(f"   Applications: {row['applications']}, Namespaces: {row['namespaces']}")
            print()
    else:
        print("⚠️  No business unit tags found")
        print("   This is expected if pods don't have user_business_unit tags")


def query_6_cost_by_cost_center(session, database, table, s3_output, cluster_name, start_date, end_date):
    """Query 6: Cost by cost center."""
    print_section("6. Cost by Cost Center")

    query = f"""
    SELECT
        resource_tags['user_cost_center'] as cost_center,
        resource_tags['user_business_unit'] as business_unit,
        COUNT(DISTINCT resource_tags['user_application']) as applications,
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

    df = wr.athena.read_sql_query(sql=query, database=database, boto3_session=session, ctas_approach=False, s3_output=s3_output)

    if not df.empty:
        total_cost = df['total_cost'].sum()
        print(f"Found {len(df)} cost centers\n")

        for idx, row in df.iterrows():
            pct = (row['total_cost'] / total_cost * 100) if total_cost > 0 else 0
            bu = row['business_unit'] if pd.notna(row['business_unit']) else 'N/A'
            print(f"💰 {row['cost_center']} ({bu})")
            print(f"   Cost: {format_cost(row['total_cost'])} ({pct:.1f}%)")
            print(f"   Applications: {row['applications']}")
            print()
    else:
        print("⚠️  No cost center tags found")
        print("   This is expected if pods don't have user_cost_center tags")


def query_7_cost_by_application(session, database, table, s3_output, cluster_name, start_date, end_date):
    """Query 7: Cost by application."""
    print_section("7. Cost by Application")

    query = f"""
    SELECT
        resource_tags['user_application'] as application,
        resource_tags['aws_eks_namespace'] as namespace,
        resource_tags['user_cost_center'] as cost_center,
        COUNT(DISTINCT resource_tags['aws_eks_workload_name']) as workloads,
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

    df = wr.athena.read_sql_query(sql=query, database=database, boto3_session=session, ctas_approach=False, s3_output=s3_output)

    if not df.empty:
        total_cost = df['total_cost'].sum()
        print(f"Found {len(df)} applications\n")

        for idx, row in df.iterrows():
            pct = (row['total_cost'] / total_cost * 100) if total_cost > 0 else 0
            cc = row['cost_center'] if pd.notna(row['cost_center']) else 'N/A'
            print(f"📱 {row['application']} (namespace: {row['namespace']})")
            print(f"   Cost: {format_cost(row['total_cost'])} ({pct:.1f}%)")
            print(f"   Cost Center: {cc}, Workloads: {row['workloads']}")
            print()
    else:
        print("⚠️  No application tags found")
        print("   This is expected if pods don't have user_application tags")


def query_8_daily_cost_trend(session, database, table, s3_output, cluster_name, start_date, end_date):
    """Query 8: Daily cost trend."""
    print_section("8. Daily Cost Trend")

    query = f"""
    SELECT
        DATE(line_item_usage_start_date) as usage_date,
        SUM(COALESCE(split_line_item_split_cost, line_item_unblended_cost)) as total_cost,
        SUM(CASE WHEN line_item_usage_type LIKE '%vCPU%' THEN COALESCE(split_line_item_split_cost, line_item_unblended_cost) ELSE 0 END) as vcpu_cost,
        SUM(CASE WHEN line_item_usage_type LIKE '%GB%' THEN COALESCE(split_line_item_split_cost, line_item_unblended_cost) ELSE 0 END) as memory_cost,
        COUNT(DISTINCT resource_tags['aws_eks_workload_name']) as unique_workloads
    FROM {database}.{table}
    WHERE
        line_item_product_code = 'AmazonEKS'
        AND resource_tags['aws_eks_cluster_name'] = '{cluster_name}'
        AND DATE(line_item_usage_start_date) >= DATE('{start_date}')
        AND DATE(line_item_usage_start_date) < DATE('{end_date}')
    GROUP BY DATE(line_item_usage_start_date)
    ORDER BY usage_date DESC
    """

    df = wr.athena.read_sql_query(sql=query, database=database, boto3_session=session, ctas_approach=False, s3_output=s3_output)

    if not df.empty:
        print(f"Daily costs for last {len(df)} days:\n")

        for idx, row in df.iterrows():
            print(f"📅 {row['usage_date']}")
            print(f"   Total: {format_cost(row['total_cost'])}")
            print(f"   - vCPU: {format_cost(row['vcpu_cost'])}")
            print(f"   - Memory: {format_cost(row['memory_cost'])}")
            print(f"   Active Workloads: {row['unique_workloads']}")
            print()
    else:
        print("❌ No daily trend data found")


def main():
    """Main execution."""
    args = setup_args()

    print("\n" + "💰" * 40)
    print("  EKS Cost Explorer - CUR 2.0")
    print("💰" * 40 + "\n")

    # Create boto3 session
    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        print(f"✅ Connected to AWS using profile: {args.profile}")
        print(f"   Region: {args.region}\n")
    except Exception as e:
        print(f"❌ Failed to create AWS session: {e}")
        return 1

    # Calculate date range
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=args.days)

    print(f"📊 Analysis Configuration:")
    print(f"   Database: {args.database}.{args.table}")
    print(f"   Cluster: {args.cluster}")
    print(f"   Date Range: {start_date} to {end_date} ({args.days} days)")
    print(f"   S3 Output: {args.s3_output}")

    try:
        # Run all queries
        query_1_total_cluster_cost(session, args.database, args.table, args.s3_output, args.cluster, start_date, end_date)
        query_2_cost_by_namespace(session, args.database, args.table, args.s3_output, args.cluster, start_date, end_date)
        query_3_cost_by_workload_type(session, args.database, args.table, args.s3_output, args.cluster, start_date, end_date)
        query_4_top_workloads(session, args.database, args.table, args.s3_output, args.cluster, start_date, end_date, limit=15)
        query_5_cost_by_business_unit(session, args.database, args.table, args.s3_output, args.cluster, start_date, end_date)
        query_6_cost_by_cost_center(session, args.database, args.table, args.s3_output, args.cluster, start_date, end_date)
        query_7_cost_by_application(session, args.database, args.table, args.s3_output, args.cluster, start_date, end_date)
        query_8_daily_cost_trend(session, args.database, args.table, args.s3_output, args.cluster, start_date, end_date)

        print_section("Summary")
        print("✅ Analysis complete!")
        print(f"\n📝 All queries executed successfully using actual CUR 2.0 tag structure")
        print(f"   - aws_eks_cluster_name")
        print(f"   - aws_eks_namespace")
        print(f"   - aws_eks_workload_name")
        print(f"   - aws_eks_workload_type")
        print(f"   - user_business_unit")
        print(f"   - user_cost_center")
        print(f"   - user_application\n")

    except Exception as e:
        print(f"\n❌ Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    exit(main())
