"""
Configuration for Cost Governance Operator
Loads settings from environment variables.
"""
import os


class Config:
    """Operator configuration from environment."""

    # AWS Configuration
    AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
    AWS_PROFILE = os.getenv('AWS_PROFILE', None)  # For local dev, None for Pod Identity

    # Athena Configuration
    ATHENA_DATABASE = os.getenv('ATHENA_DATABASE', 'billingdata')
    ATHENA_TABLE = os.getenv('ATHENA_TABLE', 'data')
    ATHENA_WORKGROUP = os.getenv('ATHENA_WORKGROUP', 'primary')
    ATHENA_S3_OUTPUT = os.getenv('ATHENA_S3_OUTPUT', 's3://athena-results-783837106602-us-east-1-an/')

    # EKS Configuration
    EKS_CLUSTER_NAME = os.getenv('EKS_CLUSTER_NAME', 'cost-demo-eks-cluster')

    # Cost Collection Configuration
    COST_LOOKBACK_DAYS = int(os.getenv('COST_LOOKBACK_DAYS', '7'))  # Query last N days
    COST_COLLECTION_INTERVAL = int(os.getenv('COST_COLLECTION_INTERVAL', '3600'))  # seconds (1 hour)

    # Prometheus Configuration
    PROMETHEUS_URL = os.getenv('PROMETHEUS_URL', 'http://prometheus-server.monitoring.svc:9090')

    # Operator Configuration
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    HEALTH_PORT = int(os.getenv('HEALTH_PORT', '8080'))

    @classmethod
    def validate(cls):
        """Validate required configuration."""
        errors = []

        # Phase 1: No validation needed yet
        # In later phases, we'll check:
        # - S3_RESULTS_BUCKET is set
        # - Prometheus is reachable
        # - Athena database exists

        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")

        return True

    @classmethod
    def display(cls):
        """Display current configuration (for logging)."""
        return {
            'aws_region': cls.AWS_REGION,
            'aws_profile': cls.AWS_PROFILE or 'Pod Identity',
            'athena_database': cls.ATHENA_DATABASE,
            'athena_table': cls.ATHENA_TABLE,
            'athena_s3_output': cls.ATHENA_S3_OUTPUT[:30] + '...' if cls.ATHENA_S3_OUTPUT else 'NOT_SET',
            'eks_cluster_name': cls.EKS_CLUSTER_NAME,
            'cost_lookback_days': cls.COST_LOOKBACK_DAYS,
            'prometheus_url': cls.PROMETHEUS_URL,
            'log_level': cls.LOG_LEVEL,
            'health_port': cls.HEALTH_PORT
        }
