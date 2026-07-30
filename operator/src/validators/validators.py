"""
Unified Validator for cost governance compliance.

Consolidates pod scanning, label validation, and resource validation
into a single class with a simple interface.

Usage:
    validator = Validator(
        required_labels=['cost-center', 'business-unit', 'team', 'application', 'environment'],
        registry=registry,
        resource_thresholds={'cpu': '4', 'memory': '16Gi', 'requiresGpuApproval': True}
    )
    summary = validator.validate_all()
"""

import logging
from typing import Dict, List, Optional
from kubernetes import client, config as k8s_config

from utils.registry import Registry

logger = logging.getLogger(__name__)


# Default namespaces to exclude from scanning
DEFAULT_EXCLUDE_NAMESPACES = [
    'kube-system',
    'kube-public',
    'kube-node-lease',
    'gatekeeper-system'
]


class ValidationResult:
    """Result of validating a single pod."""

    def __init__(self, is_valid: bool, violations: List[str] = None):
        self.is_valid = is_valid
        self.violations = violations or []

    def __bool__(self):
        return self.is_valid


class PodScanResult:
    """Result of scanning a single pod."""

    def __init__(
        self,
        name: str,
        namespace: str,
        labels: Dict[str, str],
        validation_result: ValidationResult
    ):
        self.name = name
        self.namespace = namespace
        self.labels = labels
        self.validation_result = validation_result
        self.is_compliant = validation_result.is_valid

    def __str__(self):
        status = "COMPLIANT" if self.is_compliant else "NON-COMPLIANT"
        return f"{self.namespace}/{self.name}: {status}"


class ComplianceSummary:
    """Summary of compliance scan results."""

    def __init__(self):
        self.total_pods = 0
        self.compliant_pods = 0
        self.non_compliant_pods = 0
        self.violations_by_type: Dict[str, int] = {}
        self.pod_results: List[PodScanResult] = []

    @property
    def compliance_rate(self) -> float:
        """Calculate compliance rate as percentage (0-100)."""
        if self.total_pods == 0:
            return 0.0
        return (self.compliant_pods / self.total_pods) * 100

    def add_result(self, result: PodScanResult):
        """Add a pod scan result to the summary."""
        self.total_pods += 1
        self.pod_results.append(result)

        if result.is_compliant:
            self.compliant_pods += 1
        else:
            self.non_compliant_pods += 1

            for violation in result.validation_result.violations:
                violation_type = violation.split(':')[0].strip()
                self.violations_by_type[violation_type] = \
                    self.violations_by_type.get(violation_type, 0) + 1

    def to_dict(self) -> Dict:
        """Convert summary to dictionary for CRD status update."""
        return {
            'totalPods': self.total_pods,
            'compliantPods': self.compliant_pods,
            'nonCompliantPods': self.non_compliant_pods,
            'complianceRate': round(self.compliance_rate, 2),
            'violationsByType': self.violations_by_type
        }

    def __str__(self):
        return (
            f"Compliance Summary:\n"
            f"  Total Pods: {self.total_pods}\n"
            f"  Compliant: {self.compliant_pods}\n"
            f"  Non-Compliant: {self.non_compliant_pods}\n"
            f"  Compliance Rate: {self.compliance_rate:.2f}%"
        )


class Validator:
    """
    Unified validator for cost governance compliance.

    Handles pod discovery, label validation, and resource validation
    in a single class.
    """

    def __init__(
        self,
        required_labels: List[str],
        registry: Optional[Registry] = None,
        resource_thresholds: Optional[Dict] = None,
        exclude_namespaces: Optional[List[str]] = None
    ):
        """
        Initialize validator.

        Args:
            required_labels: List of required label keys on pods
            registry: Registry for validating label values (optional)
            resource_thresholds: Dict with cpu, memory thresholds (optional)
            exclude_namespaces: Namespaces to skip during scanning
        """
        self.required_labels = required_labels
        self.registry = registry
        self.resource_thresholds = resource_thresholds or {}
        self.exclude_namespaces = exclude_namespaces or DEFAULT_EXCLUDE_NAMESPACES
        self.k8s_client = self._get_k8s_client()
        self.v1 = client.CoreV1Api(self.k8s_client)

    def _get_k8s_client(self):
        """Get Kubernetes API client."""
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        return client.ApiClient()

    def validate_all(self) -> ComplianceSummary:
        """
        Scan all pods across all namespaces and run all validators.

        Returns:
            ComplianceSummary with results from all validators
        """
        summary = ComplianceSummary()

        try:
            namespaces = self.v1.list_namespace()

            for ns in namespaces.items:
                ns_name = ns.metadata.name

                if ns_name in self.exclude_namespaces:
                    logger.debug(f"Skipping excluded namespace: {ns_name}")
                    continue

                logger.info(f"Scanning namespace: {ns_name}")
                pods = self.v1.list_namespaced_pod(ns_name)

                for pod in pods.items:
                    if pod.metadata.name.startswith('kube-'):
                        continue

                    result = self._validate_pod(pod)
                    summary.add_result(result)

                    if not result.is_compliant:
                        logger.info(
                            f"Non-compliant pod: {ns_name}/{pod.metadata.name} - "
                            f"{', '.join(result.validation_result.violations)}"
                        )

        except Exception as e:
            logger.error(f"Error during validation scan: {e}", exc_info=True)

        return summary

    def _validate_pod(self, pod) -> PodScanResult:
        """
        Run all validators against a single pod.

        Args:
            pod: Kubernetes pod object

        Returns:
            PodScanResult with combined violations from all validators
        """
        labels = pod.metadata.labels or {}
        all_violations = []

        # Check 1: Label completeness
        label_completeness_violations = self.validate_label_completeness(labels)
        all_violations.extend(label_completeness_violations)

        # Check 2: Label values (only if all labels present)
        if not label_completeness_violations:
            label_value_violations = self.validate_label_values(labels)
            all_violations.extend(label_value_violations)

        # Check 3: Resource requests presence
        resource_presence_violations = self.validate_resource_presence(pod.spec)
        all_violations.extend(resource_presence_violations)

        # Check 4: Resource threshold violations
        if not resource_presence_violations and self.resource_thresholds:
            resource_threshold_violations = self.validate_resource_values(pod.spec)
            all_violations.extend(resource_threshold_violations)

        # Build ValidationResult-compatible object
        validation_result = ValidationResult(
            is_valid=len(all_violations) == 0,
            violations=all_violations
        )

        return PodScanResult(
            name=pod.metadata.name,
            namespace=pod.metadata.namespace,
            labels=labels,
            validation_result=validation_result
        )

    def validate_label_completeness(self, labels: Dict[str, str]) -> List[str]:
        """
        Check if all required labels are present and non-empty.

        Args:
            labels: Pod labels dictionary

        Returns:
            List of violation messages (empty if compliant)
        """
        violations = []
        for required in self.required_labels:
            if required not in labels or not labels[required]:
                violations.append(f"Missing required label: {required}")
        return violations

    def validate_label_values(self, labels: Dict[str, str]) -> List[str]:
        """
        Validate label values against registry.

        Args:
            labels: Pod labels dictionary

        Returns:
            List of violation messages (empty if compliant)
        """
        if not self.registry:
            return []

        violations = []

        business_unit = labels.get('business-unit', '')
        cost_center = labels.get('cost-center', '')
        team = labels.get('team', '')
        environment = labels.get('environment', '')

        # Validate business unit
        if business_unit and not self.registry.validate_business_unit(business_unit):
            valid_bus = self.registry.get_valid_business_units()
            violations.append(
                f"Invalid business-unit: '{business_unit}'. Valid values: {', '.join(valid_bus)}"
            )

        # Validate cost center (only if BU is valid)
        if business_unit and cost_center:
            if not self.registry.validate_cost_center(business_unit, cost_center):
                valid_ccs = self.registry.get_valid_cost_centers(business_unit)
                violations.append(
                    f"Invalid cost-center: '{cost_center}' for business-unit: '{business_unit}'. "
                    f"Valid values: {', '.join(valid_ccs)}"
                )

        # Validate team (only if BU is valid)
        if business_unit and team:
            if not self.registry.validate_team(business_unit, team):
                valid_teams = self.registry.get_valid_teams(business_unit)
                violations.append(
                    f"Invalid team: '{team}' for business-unit: '{business_unit}'. "
                    f"Valid values: {', '.join(valid_teams)}"
                )

        # Validate environment
        if environment and not self.registry.validate_environment(environment):
            valid_envs = self.registry.valid_environments or ['(none configured)']
            violations.append(
                f"Invalid environment: '{environment}'. Valid values: {', '.join(valid_envs)}"
            )

        return violations

    def validate_resource_presence(self, pod_spec) -> List[str]:
        """
        Check that all containers have CPU and memory resource requests.

        Args:
            pod_spec: Pod spec object

        Returns:
            List of violation messages (empty if compliant)
        """
        violations = []

        for container in pod_spec.containers:
            if not container.resources or not container.resources.requests:
                violations.append(
                    f"Container '{container.name}' missing resource requests (cpu/memory)"
                )
                continue

            requests = container.resources.requests
            if 'cpu' not in requests:
                violations.append(
                    f"Container '{container.name}' missing CPU request"
                )
            if 'memory' not in requests:
                violations.append(
                    f"Container '{container.name}' missing memory request"
                )

        return violations

    def validate_resource_values(self, pod_spec) -> List[str]:
        """
        Check that container resource requests do not exceed thresholds.

        Args:
            pod_spec: Pod spec object

        Returns:
            List of violation messages (empty if compliant)
        """
        violations = []

        cpu_threshold = self.resource_thresholds.get('cpu')
        memory_threshold = self.resource_thresholds.get('memory')

        for container in pod_spec.containers:
            if not container.resources or not container.resources.requests:
                continue

            requests = container.resources.requests

            # Check CPU threshold
            if cpu_threshold and 'cpu' in requests:
                cpu_value = self._parse_cpu(requests['cpu'])
                cpu_limit = self._parse_cpu(cpu_threshold)
                if cpu_value > cpu_limit:
                    violations.append(
                        f"Container '{container.name}' requests {requests['cpu']} CPU, "
                        f"exceeds threshold of {cpu_threshold}"
                    )

            # Check memory threshold
            if memory_threshold and 'memory' in requests:
                mem_value = self._parse_memory(requests['memory'])
                mem_limit = self._parse_memory(memory_threshold)
                if mem_value > mem_limit:
                    violations.append(
                        f"Container '{container.name}' requests {requests['memory']} memory, "
                        f"exceeds threshold of {memory_threshold}"
                    )

        return violations

    @staticmethod
    def _parse_cpu(cpu_str: str) -> float:
        """Parse CPU string to cores (float)."""
        cpu_str = str(cpu_str)
        if cpu_str.endswith('m'):
            return float(cpu_str[:-1]) / 1000.0
        return float(cpu_str)

    @staticmethod
    def _parse_memory(mem_str: str) -> float:
        """Parse memory string to bytes (float)."""
        mem_str = str(mem_str)
        units = {
            'Ki': 1024,
            'Mi': 1024 ** 2,
            'Gi': 1024 ** 3,
            'Ti': 1024 ** 4,
            'K': 1000,
            'M': 1000 ** 2,
            'G': 1000 ** 3,
            'T': 1000 ** 4,
        }
        for suffix, multiplier in units.items():
            if mem_str.endswith(suffix):
                return float(mem_str[:-len(suffix)]) * multiplier
        return float(mem_str)
