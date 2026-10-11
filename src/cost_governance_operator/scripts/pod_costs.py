# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Pod-level cost report.

Prints per-pod EKS costs from CUR 2.0 (Split-Cost Allocation Data), grouped by
the individual pod resource id. Reuses the operator's athena_helper (plain boto3,
no awswrangler dependency).

Usage:
    uv run python src/cost_governance_operator/scripts/pod_costs.py \\
        --profile brdcost2 \\
        --database billingdata --table data \\
        --cluster cost-demo-eks-cluster \\
        --s3-output s3://my-bucket/queryresults/ \\
        --days 10 --limit 25
"""

import argparse
from datetime import datetime, timedelta, timezone

import boto3

from cost_governance_operator.utils import athena_helper


def parse_args():
    p = argparse.ArgumentParser(description="Per-pod EKS cost report from CUR 2.0")
    p.add_argument("--profile", default="brdcost2", help="AWS profile")
    p.add_argument("--region", default="us-east-1", help="AWS region")
    p.add_argument("--database", default="billingdata", help="Athena database")
    p.add_argument("--table", default="data", help="CUR table")
    p.add_argument("--cluster", default="cost-demo-eks-cluster", help="EKS cluster name")
    p.add_argument("--s3-output", required=True, help="S3 location for Athena query results")
    p.add_argument("--days", type=int, default=7, help="Look back this many days")
    p.add_argument("--limit", type=int, default=25, help="Max pods to show (top N by cost)")
    return p.parse_args()


def main():
    args = parse_args()

    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=args.days)

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    athena = session.client("athena")

    query = athena_helper.build_top_cost_pods_query(
        args.database,
        args.table,
        args.cluster,
        start_date.isoformat(),
        end_date.isoformat(),
        limit=args.limit,
    )

    print(f"\nPod-level costs for cluster '{args.cluster}' "
          f"({start_date} to {end_date}, top {args.limit} by cost)\n")

    query_id = athena_helper.execute_athena_query(
        athena, query, args.database, args.s3_output
    )
    if not query_id:
        print("Query failed. Check credentials, database/table, and S3 output location.")
        return 1

    rows = athena_helper.get_query_results(athena, query_id)
    if not rows:
        print("No pod cost data returned for this cluster/time range.")
        return 0

    # Column widths
    header = f"{'POD (resource id)':<40} {'NAMESPACE':<20} {'WORKLOAD':<28} {'COST CENTER':<14} {'COST':>10}"
    print(header)
    print("-" * len(header))

    total = 0.0
    for r in rows:
        resource_id = (r.get("line_item_resource_id") or "")[-40:]
        namespace = (r.get("namespace") or "-")[:20]
        workload = (r.get("pod_name") or "-")[:28]
        cost_center = (r.get("cost_center") or "-")[:14]
        cost = float(r.get("total_cost") or 0)
        total += cost
        print(f"{resource_id:<40} {namespace:<20} {workload:<28} {cost_center:<14} ${cost:>9.4f}")

    print("-" * len(header))
    print(f"{'TOTAL (shown)':<104} ${total:>9.4f}\n")
    return 0


if __name__ == "__main__":
    exit(main())
