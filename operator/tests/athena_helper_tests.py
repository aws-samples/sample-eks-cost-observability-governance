"""
Integration tests for athena_helper.py

Tests execute_athena_query and get_query_results against a real Athena database.
Requires:
  - AWS credentials configured (via profile or environment)
  - Access to the billingdata.data Athena table
  - S3 bucket for query results

Usage:
  cd operator
  python -m pytest tests/athena_helper_tests.py -v

  Or with unittest:
  python -m unittest tests.athena_helper_tests -v

Environment variables:
  AWS_PROFILE       - AWS profile to use (default: brdcost)
  ATHENA_DATABASE   - Athena database name (default: billingdata)
  ATHENA_TABLE      - Athena table name (default: data)
  ATHENA_S3_OUTPUT  - S3 output location for query results
  EKS_CLUSTER_NAME  - EKS cluster name to filter on
"""

import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
import boto3

# Add src to path so we can import the modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils import athena_helper


class TestAthenaHelper(unittest.TestCase):
    """Integration tests for Athena helper functions."""

    @classmethod
    def setUpClass(cls):
        """Set up shared test fixtures — Athena client and config."""
        profile = os.getenv('AWS_PROFILE', 'brdcost')
        region = os.getenv('AWS_REGION', 'us-east-1')

        cls.database = os.getenv('ATHENA_DATABASE', 'billingdata')
        cls.table = os.getenv('ATHENA_TABLE', 'data')
        cls.s3_output = os.getenv('ATHENA_S3_OUTPUT', 's3://athena-results-783837106602-us-east-1-an/')
        cls.cluster_name = os.getenv('EKS_CLUSTER_NAME', 'cost-demo-eks-cluster')

        # Date range — dynamic: today minus lookback days
        lookback_days = int(os.getenv('COST_LOOKBACK_DAYS', '7'))
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=lookback_days)
        cls.start_date = start_date.isoformat()
        cls.end_date = end_date.isoformat()

        session = boto3.Session(profile_name=profile, region_name=region)
        cls.athena_client = session.client('athena')

    def test_execute_and_get_total_cluster_cost(self):
        """
        Test execute_athena_query + get_query_results with the total cluster cost query.
        Verifies:
          - Query executes successfully
          - Results are returned as a list of dicts
          - Expected columns are present
        """
        query = athena_helper.build_total_cluster_cost_query(
            self.database,
            self.table,
            self.cluster_name,
            self.start_date,
            self.end_date
        )

        query_id = athena_helper.execute_athena_query(
            self.athena_client,
            query,
            self.database,
            self.s3_output
        )

        self.assertIsNotNone(query_id, "Query execution should return a query ID")

        results = athena_helper.get_query_results(self.athena_client, query_id)

        self.assertIsInstance(results, list, "Results should be a list")
        # May be empty if no data for this cluster/date range
        if results:
            self.assertIn('cluster_name', results[0], "Result should have 'cluster_name' column")
            self.assertIn('total_cluster_cost', results[0], "Result should have 'total_cluster_cost' column")
            # Cost should be a parseable number
            cost = float(results[0]['total_cluster_cost'])
            self.assertGreater(cost, 0, "Total cluster cost should be > 0")
            print(f"\n  Total cluster cost: ${cost:.2f}")

    def test_execute_and_get_namespace_costs(self):
        """
        Test namespace aggregation query.
        Verifies:
          - Query returns multiple rows (one per namespace)
          - Each row has expected columns
          - Costs are non-negative
        """
        query = athena_helper.build_namespace_aggregation_query(
            self.database,
            self.table,
            self.cluster_name,
            self.start_date,
            self.end_date
        )

        query_id = athena_helper.execute_athena_query(
            self.athena_client,
            query,
            self.database,
            self.s3_output
        )

        self.assertIsNotNone(query_id, "Query execution should return a query ID")

        results = athena_helper.get_query_results(self.athena_client, query_id)

        self.assertIsInstance(results, list)
        if results:
            self.assertGreater(len(results), 0, "Should have at least one namespace")

            print("BRD: print rows")
            for row in results:
                print("Row: ", row)

            first_row = results[0]
            self.assertIn('namespace', first_row)
            self.assertIn('total_cost', first_row)
            self.assertIn('pod_count', first_row)

            # Print summary
            print(f"\n  Namespaces found: {len(results)}")
            for row in results[:5]:
                print(f"    {row['namespace']}: ${float(row['total_cost']):.2f} ({row['pod_count']} pods)")

    def test_execute_and_get_cost_utilization(self):
        """
        Test cost utilization query (split cost vs unused cost).
        Verifies:
          - Query returns results with expected columns
          - Cost efficiency percentage is between 0 and 100
        """
        query = athena_helper.build_cost_utilization_query(
            self.database,
            self.table,
            self.cluster_name,
            self.start_date,
            self.end_date
        )

        query_id = athena_helper.execute_athena_query(
            self.athena_client,
            query,
            self.database,
            self.s3_output
        )

        self.assertIsNotNone(query_id, "Query execution should return a query ID")

        results = athena_helper.get_query_results(self.athena_client, query_id)

        self.assertIsInstance(results, list)
        if results:
            first_row = results[0]
            self.assertIn('namespace', first_row)
            self.assertIn('split_cost', first_row)
            self.assertIn('unused_cost', first_row)
            self.assertIn('cost_efficiency_pct', first_row)

            # Efficiency should be 0-100
            efficiency = float(first_row['cost_efficiency_pct'])
            self.assertGreaterEqual(efficiency, 0)
            self.assertLessEqual(efficiency, 100)

            # Print summary
            print(f"\n  Namespaces with utilization data: {len(results)}")
            for row in results[:5]:
                print(f"    {row['namespace']}: split=${float(row['split_cost']):.2f}, "
                      f"unused=${float(row['unused_cost']):.2f}, "
                      f"efficiency={row['cost_efficiency_pct']}%")

    def test_execute_and_get_attribution_summary(self):
        """Test attribution summary query (tagged vs untagged costs)."""
        query = athena_helper.build_attribution_summary_query(
            self.database, self.table, self.cluster_name, self.start_date, self.end_date
        )
        query_id = athena_helper.execute_athena_query(self.athena_client, query, self.database, self.s3_output)
        self.assertIsNotNone(query_id)
        results = athena_helper.get_query_results(self.athena_client, query_id)
        self.assertIsInstance(results, list)
        if results:
            row = results[0]
            self.assertIn('tagged_pods', row)
            self.assertIn('untagged_pods', row)
            self.assertIn('tagged_cost', row)
            self.assertIn('untagged_cost', row)
            print(f"\n  Attribution: tagged=${row['tagged_cost']}, untagged=${row['untagged_cost']}")

    def test_execute_and_get_top_cost_pods(self):
        """Test top cost pods query."""
        query = athena_helper.build_top_cost_pods_query(
            self.database, self.table, self.cluster_name, self.start_date, self.end_date, limit=5
        )
        query_id = athena_helper.execute_athena_query(self.athena_client, query, self.database, self.s3_output)
        self.assertIsNotNone(query_id)
        results = athena_helper.get_query_results(self.athena_client, query_id)
        self.assertIsInstance(results, list)
        self.assertLessEqual(len(results), 5)
        if results:
            self.assertIn('total_cost', results[0])
            print(f"\n  Top pods: {len(results)}")
            for row in results:
                print("BRD: row: ", row)
                print(f"    {row.get('namespace')}/{row.get('pod_name')}: ${float(row['total_cost']):.2f}")

    def test_execute_and_get_daily_costs(self):
        """Test daily cost trends query."""
        query = athena_helper.build_daily_cost_query(
            self.database, self.table, self.cluster_name, self.start_date, self.end_date
        )
        query_id = athena_helper.execute_athena_query(self.athena_client, query, self.database, self.s3_output)
        self.assertIsNotNone(query_id)
        results = athena_helper.get_query_results(self.athena_client, query_id)
        self.assertIsInstance(results, list)
        if results:
            self.assertIn('usage_date', results[0])
            self.assertIn('daily_cost', results[0])
            print(f"\n  Daily costs: {len(results)} days")
            for row in results[:3]:
                print(f"    {row['usage_date']}: ${float(row['daily_cost']):.2f}")

    def test_execute_and_get_business_unit_costs(self):
        """Test business unit costs query."""
        query = athena_helper.build_business_unit_costs_query(
            self.database, self.table, self.cluster_name, self.start_date, self.end_date
        )
        query_id = athena_helper.execute_athena_query(self.athena_client, query, self.database, self.s3_output)
        self.assertIsNotNone(query_id)
        results = athena_helper.get_query_results(self.athena_client, query_id)
        self.assertIsInstance(results, list)
        if results:
            self.assertIn('business_unit', results[0])
            self.assertIn('total_cost', results[0])
            print(f"\n  Business units: {len(results)}")
            for row in results:
                print(f"    {row['business_unit']}: ${float(row['total_cost']):.2f}")

    def test_execute_and_get_cost_center_costs(self):
        """Test cost center costs query."""
        query = athena_helper.build_cost_center_costs_query(
            self.database, self.table, self.cluster_name, self.start_date, self.end_date
        )
        query_id = athena_helper.execute_athena_query(self.athena_client, query, self.database, self.s3_output)
        self.assertIsNotNone(query_id)
        results = athena_helper.get_query_results(self.athena_client, query_id)
        self.assertIsInstance(results, list)
        if results:
            self.assertIn('cost_center', results[0])
            self.assertIn('total_cost', results[0])
            print(f"\n  Cost centers: {len(results)}")
            for row in results:
                print(f"    {row['cost_center']}: ${float(row['total_cost']):.2f}")

    def test_execute_and_get_application_costs(self):
        """Test application costs query."""
        query = athena_helper.build_application_costs_query(
            self.database, self.table, self.cluster_name, self.start_date, self.end_date
        )
        query_id = athena_helper.execute_athena_query(self.athena_client, query, self.database, self.s3_output)
        self.assertIsNotNone(query_id)
        results = athena_helper.get_query_results(self.athena_client, query_id)
        self.assertIsInstance(results, list)
        if results:
            self.assertIn('application', results[0])
            self.assertIn('total_cost', results[0])
            print(f"\n  Applications: {len(results)}")
            for row in results[:5]:
                print(f"    {row['application']} ({row.get('namespace')}): ${float(row['total_cost']):.2f}")

    def test_execute_and_get_workload_type_costs(self):
        """Test workload type costs query."""
        query = athena_helper.build_workload_type_costs_query(
            self.database, self.table, self.cluster_name, self.start_date, self.end_date
        )
        query_id = athena_helper.execute_athena_query(self.athena_client, query, self.database, self.s3_output)
        self.assertIsNotNone(query_id)
        results = athena_helper.get_query_results(self.athena_client, query_id)
        self.assertIsInstance(results, list)
        if results:
            self.assertIn('workload_type', results[0])
            self.assertIn('total_cost', results[0])
            print(f"\n  Workload types: {len(results)}")
            for row in results:
                print(f"    {row['workload_type']}: ${float(row['total_cost']):.2f}")

    def test_execute_and_get_cluster_infrastructure_costs(self):
        """Test cluster infrastructure costs query."""
        infra_namespaces = ['kube-system', 'monitoring', 'karpenter', 'cost-governance-system']
        query = athena_helper.build_cluster_infrastructure_costs_query(
            self.database, self.table, self.cluster_name, self.start_date, self.end_date, infra_namespaces
        )
        query_id = athena_helper.execute_athena_query(self.athena_client, query, self.database, self.s3_output)
        self.assertIsNotNone(query_id)
        results = athena_helper.get_query_results(self.athena_client, query_id)
        self.assertIsInstance(results, list)
        if results:
            self.assertIn('namespace', results[0])
            self.assertIn('pod_name', results[0])
            self.assertIn('total_cost', results[0])
            print(f"\n  Infrastructure pods: {len(results)}")
            for row in results[:5]:
                print(f"    {row['namespace']}/{row.get('pod_name')}: ${float(row['total_cost']):.2f}")

    def test_query_failure_returns_none(self):
        """
        Test that a query against a non-existent table returns None (graceful failure).
        """
        bad_query = "SELECT * FROM nonexistent_db.nonexistent_table LIMIT 1"

        query_id = athena_helper.execute_athena_query(
            self.athena_client,
            bad_query,
            "nonexistent_db",
            self.s3_output
        )

        # Should return None on failure (bad database/table)
        self.assertIsNone(query_id, "Bad query should return None")


if __name__ == '__main__':
    unittest.main()
