# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Integration tests for athena_helper.

Tests execute_athena_query and get_query_results against a real Athena database.
Requires:
  - AWS credentials configured (via profile or environment)
  - Access to the billingdata.data Athena table
  - S3 bucket for query results

Usage:
  make test-integ AWS_PROFILE=<profile>

Environment variables:
  AWS_PROFILE       - AWS profile to use (default: brdcost)
  ATHENA_DATABASE   - Athena database name (default: billingdata)
  ATHENA_TABLE      - Athena table name (default: data)
  ATHENA_S3_OUTPUT  - S3 output location for query results
  EKS_CLUSTER_NAME  - EKS cluster name to filter on
"""

import os
from datetime import datetime, timezone, timedelta

import boto3
import pytest

from cost_governance_operator.utils import athena_helper


@pytest.fixture(scope="module")
def athena_config():
    """Shared Athena configuration from environment."""
    profile = os.getenv("AWS_PROFILE")
    region = os.getenv("AWS_REGION", "us-east-1")

    # Required env vars — skip with clear message if not set
    required_vars = {
        "AWS_PROFILE": profile,
        "ATHENA_S3_OUTPUT": os.getenv("ATHENA_S3_OUTPUT"),
        "ATHENA_DATABASE": os.getenv("ATHENA_DATABASE"),
        "ATHENA_TABLE": os.getenv("ATHENA_TABLE"),
        "EKS_CLUSTER_NAME": os.getenv("EKS_CLUSTER_NAME"),
    }

    missing = [k for k, v in required_vars.items() if not v]
    if missing:
        pytest.skip(
            f"Integration tests require the following environment variables: {', '.join(missing)}. "
            f"Example: ATHENA_S3_OUTPUT='s3://my-bucket/queryresults/' "
            f"ATHENA_DATABASE='my_cur_db' ATHENA_TABLE='my_cur_table' "
            f"EKS_CLUSTER_NAME='my-cluster' AWS_PROFILE='my-profile' "
            f"make test-integ"
        )

    lookback_days = int(os.getenv("COST_LOOKBACK_DAYS", "7"))
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=lookback_days)

    config = {
        "database": required_vars["ATHENA_DATABASE"],
        "table": required_vars["ATHENA_TABLE"],
        "s3_output": required_vars["ATHENA_S3_OUTPUT"],
        "cluster_name": required_vars["EKS_CLUSTER_NAME"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "profile": profile,
        "region": region,
    }

    print("\n=== Integration Test Configuration ===")
    for key, value in config.items():
        print(f"  {key}: {value}")
    print("======================================\n")

    return config


@pytest.fixture(scope="module")
def athena_client(athena_config):
    """Boto3 Athena client."""
    session = boto3.Session(profile_name=athena_config["profile"], region_name=athena_config["region"])
    return session.client("athena")


@pytest.mark.integration
class TestAthenaHelper:
    """Integration tests for Athena helper functions."""

    def test_total_cluster_cost(self, athena_client, athena_config):
        """Query executes and returns parseable cost data."""
        query = athena_helper.build_total_cluster_cost_query(
            athena_config["database"],
            athena_config["table"],
            athena_config["cluster_name"],
            athena_config["start_date"],
            athena_config["end_date"],
        )

        query_id = athena_helper.execute_athena_query(
            athena_client, query, athena_config["database"], athena_config["s3_output"]
        )
        assert query_id is not None, "Query execution should return a query ID"

        results = athena_helper.get_query_results(athena_client, query_id)
        assert isinstance(results, list)

        if results:
            assert "cluster_name" in results[0]
            assert "total_cluster_cost" in results[0]
            cost = float(results[0]["total_cluster_cost"])
            assert cost > 0

    def test_namespace_costs(self, athena_client, athena_config):
        """Returns multiple rows with expected columns."""
        query = athena_helper.build_namespace_aggregation_query(
            athena_config["database"],
            athena_config["table"],
            athena_config["cluster_name"],
            athena_config["start_date"],
            athena_config["end_date"],
        )

        query_id = athena_helper.execute_athena_query(
            athena_client, query, athena_config["database"], athena_config["s3_output"]
        )
        assert query_id is not None

        results = athena_helper.get_query_results(athena_client, query_id)
        assert isinstance(results, list)

        if results:
            assert len(results) > 0
            assert "namespace" in results[0]
            assert "total_cost" in results[0]
            assert "pod_count" in results[0]

    def test_cost_utilization(self, athena_client, athena_config):
        """Cost efficiency percentage is between 0 and 100."""
        query = athena_helper.build_cost_utilization_query(
            athena_config["database"],
            athena_config["table"],
            athena_config["cluster_name"],
            athena_config["start_date"],
            athena_config["end_date"],
        )

        query_id = athena_helper.execute_athena_query(
            athena_client, query, athena_config["database"], athena_config["s3_output"]
        )
        assert query_id is not None

        results = athena_helper.get_query_results(athena_client, query_id)
        assert isinstance(results, list)

        if results:
            row = results[0]
            assert "namespace" in row
            assert "split_cost" in row
            assert "unused_cost" in row
            assert "cost_efficiency_pct" in row
            efficiency = float(row["cost_efficiency_pct"])
            assert 0 <= efficiency <= 100

    def test_attribution_summary(self, athena_client, athena_config):
        """Returns tagged vs untagged cost breakdown."""
        query = athena_helper.build_attribution_summary_query(
            athena_config["database"],
            athena_config["table"],
            athena_config["cluster_name"],
            athena_config["start_date"],
            athena_config["end_date"],
        )

        query_id = athena_helper.execute_athena_query(
            athena_client, query, athena_config["database"], athena_config["s3_output"]
        )
        assert query_id is not None

        results = athena_helper.get_query_results(athena_client, query_id)
        assert isinstance(results, list)

        if results:
            row = results[0]
            assert "tagged_pods" in row
            assert "untagged_pods" in row
            assert "tagged_cost" in row
            assert "untagged_cost" in row

    def test_top_cost_pods(self, athena_client, athena_config):
        """Returns at most N pods with cost data."""
        query = athena_helper.build_top_cost_pods_query(
            athena_config["database"],
            athena_config["table"],
            athena_config["cluster_name"],
            athena_config["start_date"],
            athena_config["end_date"],
            limit=5,
        )

        query_id = athena_helper.execute_athena_query(
            athena_client, query, athena_config["database"], athena_config["s3_output"]
        )
        assert query_id is not None

        results = athena_helper.get_query_results(athena_client, query_id)
        assert isinstance(results, list)
        assert len(results) <= 5

        if results:
            assert "total_cost" in results[0]

    def test_daily_costs(self, athena_client, athena_config):
        """Returns daily cost trend data."""
        query = athena_helper.build_daily_cost_query(
            athena_config["database"],
            athena_config["table"],
            athena_config["cluster_name"],
            athena_config["start_date"],
            athena_config["end_date"],
        )

        query_id = athena_helper.execute_athena_query(
            athena_client, query, athena_config["database"], athena_config["s3_output"]
        )
        assert query_id is not None

        results = athena_helper.get_query_results(athena_client, query_id)
        assert isinstance(results, list)

        if results:
            assert "usage_date" in results[0]
            assert "daily_cost" in results[0]

    def test_business_unit_costs(self, athena_client, athena_config):
        """Returns cost data grouped by business unit."""
        query = athena_helper.build_business_unit_costs_query(
            athena_config["database"],
            athena_config["table"],
            athena_config["cluster_name"],
            athena_config["start_date"],
            athena_config["end_date"],
        )

        query_id = athena_helper.execute_athena_query(
            athena_client, query, athena_config["database"], athena_config["s3_output"]
        )
        assert query_id is not None

        results = athena_helper.get_query_results(athena_client, query_id)
        assert isinstance(results, list)

        if results:
            assert "business_unit" in results[0]
            assert "total_cost" in results[0]

    def test_cost_center_costs(self, athena_client, athena_config):
        """Returns cost data grouped by cost center."""
        query = athena_helper.build_cost_center_costs_query(
            athena_config["database"],
            athena_config["table"],
            athena_config["cluster_name"],
            athena_config["start_date"],
            athena_config["end_date"],
        )

        query_id = athena_helper.execute_athena_query(
            athena_client, query, athena_config["database"], athena_config["s3_output"]
        )
        assert query_id is not None

        results = athena_helper.get_query_results(athena_client, query_id)
        assert isinstance(results, list)

        if results:
            assert "cost_center" in results[0]
            assert "total_cost" in results[0]

    def test_application_costs(self, athena_client, athena_config):
        """Returns cost data grouped by application."""
        query = athena_helper.build_application_costs_query(
            athena_config["database"],
            athena_config["table"],
            athena_config["cluster_name"],
            athena_config["start_date"],
            athena_config["end_date"],
        )

        query_id = athena_helper.execute_athena_query(
            athena_client, query, athena_config["database"], athena_config["s3_output"]
        )
        assert query_id is not None

        results = athena_helper.get_query_results(athena_client, query_id)
        assert isinstance(results, list)

        if results:
            assert "application" in results[0]
            assert "total_cost" in results[0]

    def test_workload_type_costs(self, athena_client, athena_config):
        """Returns cost data grouped by workload type."""
        query = athena_helper.build_workload_type_costs_query(
            athena_config["database"],
            athena_config["table"],
            athena_config["cluster_name"],
            athena_config["start_date"],
            athena_config["end_date"],
        )

        query_id = athena_helper.execute_athena_query(
            athena_client, query, athena_config["database"], athena_config["s3_output"]
        )
        assert query_id is not None

        results = athena_helper.get_query_results(athena_client, query_id)
        assert isinstance(results, list)

        if results:
            assert "workload_type" in results[0]
            assert "total_cost" in results[0]

    def test_cluster_infrastructure_costs(self, athena_client, athena_config):
        """Returns pod-level costs for infrastructure namespaces."""
        infra_namespaces = ["kube-system", "monitoring", "karpenter", "cost-governance-system"]
        query = athena_helper.build_cluster_infrastructure_costs_query(
            athena_config["database"],
            athena_config["table"],
            athena_config["cluster_name"],
            athena_config["start_date"],
            athena_config["end_date"],
            infra_namespaces,
        )

        query_id = athena_helper.execute_athena_query(
            athena_client, query, athena_config["database"], athena_config["s3_output"]
        )
        assert query_id is not None

        results = athena_helper.get_query_results(athena_client, query_id)
        assert isinstance(results, list)

        if results:
            assert "namespace" in results[0]
            assert "pod_name" in results[0]
            assert "total_cost" in results[0]

    def test_query_failure_returns_none(self, athena_client, athena_config):
        """A query against a non-existent table returns None gracefully."""
        bad_query = "SELECT * FROM nonexistent_db.nonexistent_table LIMIT 1"

        query_id = athena_helper.execute_athena_query(
            athena_client, bad_query, "nonexistent_db", athena_config["s3_output"]
        )

        assert query_id is None, "Bad query should return None"
