"""
Cluster infrastructure cost attribution configuration.

Defines how to categorize and attribute costs for system namespaces
and cluster infrastructure components.
"""

from typing import Dict, List, NamedTuple, Optional


class ComponentConfig(NamedTuple):
    """Configuration for a cluster infrastructure component."""
    category: str           # "platform", "observability", "operations", "governance"
    description: str        # Human-readable description
    pod_patterns: List[str] # Pod name patterns to match (prefix matching)


# Namespace-level categorization (default, can be overridden via registry)
NAMESPACE_CATEGORIES = {
    'kube-system': 'platform',
    'monitoring': 'observability',
    'karpenter': 'operations',
    'cost-governance-system': 'governance'
}


def set_namespace_categories(categories: Dict[str, str]):
    """
    Override namespace categories from registry.

    Called from main.py after loading the registry ConfigMap.

    Args:
        categories: Dict mapping namespace name to category string
    """
    global NAMESPACE_CATEGORIES
    NAMESPACE_CATEGORIES = categories


# Component-level configuration
# Maps pod name prefixes to specific component categories
COMPONENT_CONFIGS: Dict[str, ComponentConfig] = {
    # Platform Components (kube-system)
    'aws-node': ComponentConfig(
        category='platform',
        description='AWS VPC CNI - Network connectivity',
        pod_patterns=['aws-node-']
    ),
    'coredns': ComponentConfig(
        category='platform',
        description='CoreDNS - DNS service',
        pod_patterns=['coredns-']
    ),
    'kube-proxy': ComponentConfig(
        category='platform',
        description='Kube Proxy - Network proxy',
        pod_patterns=['kube-proxy-']
    ),
    'ebs-csi-controller': ComponentConfig(
        category='platform',
        description='EBS CSI Driver - Persistent storage controller',
        pod_patterns=['ebs-csi-controller-']
    ),
    'ebs-csi-node': ComponentConfig(
        category='platform',
        description='EBS CSI Driver - Node agent',
        pod_patterns=['ebs-csi-node-']
    ),
    'pod-identity-agent': ComponentConfig(
        category='platform',
        description='EKS Pod Identity - IAM authentication',
        pod_patterns=['eks-pod-identity-agent-']
    ),
    'vpc-resource-controller': ComponentConfig(
        category='platform',
        description='VPC Resource Controller - ENI management',
        pod_patterns=['vpc-resource-controller-']
    ),
    'metrics-server': ComponentConfig(
        category='platform',
        description='Metrics Server - Resource metrics',
        pod_patterns=['metrics-server-']
    ),

    # Observability Components (monitoring namespace)
    'prometheus': ComponentConfig(
        category='observability',
        description='Prometheus - Metrics collection',
        pod_patterns=['prometheus-']
    ),
    'grafana': ComponentConfig(
        category='observability',
        description='Grafana - Metrics visualization',
        pod_patterns=['grafana-']
    ),
    'node-exporter': ComponentConfig(
        category='observability',
        description='Node Exporter - Node metrics',
        pod_patterns=['prometheus-node-exporter-', 'node-exporter-']
    ),
    'kube-state-metrics': ComponentConfig(
        category='observability',
        description='Kube State Metrics - K8s object metrics',
        pod_patterns=['kube-state-metrics-']
    ),
    'prometheus-operator': ComponentConfig(
        category='observability',
        description='Prometheus Operator - Monitoring management',
        pod_patterns=['prometheus-operator-']
    ),
    'alertmanager': ComponentConfig(
        category='observability',
        description='Alertmanager - Alert handling',
        pod_patterns=['alertmanager-']
    ),

    # Operations Components (karpenter namespace)
    'karpenter': ComponentConfig(
        category='operations',
        description='Karpenter - Node autoscaling',
        pod_patterns=['karpenter-']
    ),

    # Cost Governance Components
    'cost-governance-operator': ComponentConfig(
        category='governance',
        description='Cost Governance Operator - Cost attribution and compliance',
        pod_patterns=['cost-governance-operator-']
    ),
}


# Category descriptions
CATEGORY_DESCRIPTIONS = {
    'platform': 'Core Kubernetes platform services (networking, DNS, storage, identity)',
    'observability': 'Monitoring, metrics, and logging infrastructure',
    'operations': 'Cluster operations and automation (autoscaling, maintenance)',
    'governance': 'Cost governance and compliance monitoring'
}


def get_component_config(pod_name: str, namespace: str) -> Optional[ComponentConfig]:
    """
    Get component configuration for a pod.

    Args:
        pod_name: Pod name (e.g., "kube-proxy-abc123")
        namespace: Namespace name

    Returns:
        ComponentConfig if matched, None otherwise
    """
    # Try to match against component patterns
    for component_name, config in COMPONENT_CONFIGS.items():
        for pattern in config.pod_patterns:
            if pod_name.startswith(pattern):
                return config

    return None


def get_namespace_category(namespace: str) -> Optional[str]:
    """
    Get category for a namespace.

    Args:
        namespace: Namespace name

    Returns:
        Category name if matched, None otherwise
    """
    return NAMESPACE_CATEGORIES.get(namespace)


def is_cluster_infrastructure(namespace: str) -> bool:
    """
    Check if a namespace contains cluster infrastructure.

    Args:
        namespace: Namespace name

    Returns:
        True if namespace is cluster infrastructure, False otherwise
    """
    return namespace in NAMESPACE_CATEGORIES


def get_all_infrastructure_namespaces() -> List[str]:
    """
    Get list of all cluster infrastructure namespaces.

    Returns:
        List of namespace names
    """
    return list(NAMESPACE_CATEGORIES.keys())


def get_component_name(pod_name: str) -> str:
    """
    Extract component name from pod name.

    Args:
        pod_name: Full pod name (e.g., "kube-proxy-abc123")

    Returns:
        Component name (e.g., "kube-proxy")
    """
    # Try to match known components
    for component_name, config in COMPONENT_CONFIGS.items():
        for pattern in config.pod_patterns:
            if pod_name.startswith(pattern):
                return component_name

    # Fallback: extract base name (everything before first dash and hash)
    # Example: "some-component-7d8f9-xyz" -> "some-component"
    parts = pod_name.split('-')

    # If last part looks like a hash (alphanumeric, 5+ chars), remove it
    if len(parts) > 1 and len(parts[-1]) >= 5:
        parts = parts[:-1]

    # If second-to-last part looks like a hash too, remove it
    if len(parts) > 1 and len(parts[-1]) >= 5 and parts[-1].isalnum():
        parts = parts[:-1]

    return '-'.join(parts) if parts else pod_name
