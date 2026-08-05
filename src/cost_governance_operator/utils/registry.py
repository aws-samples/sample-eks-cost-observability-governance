"""
Registry management - loads and parses cost governance registry from ConfigMap.
"""
import yaml
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class Registry:
    """Cost governance registry parser and validator."""

    def __init__(self, registry_data: Dict):
        """
        Initialize registry from ConfigMap data.

        Args:
            registry_data: Parsed YAML from ConfigMap
        """
        self.data = registry_data
        self.business_units = {}
        self.infrastructure_namespaces = {}
        self._parse_registry()

    def _parse_registry(self):
        """Parse registry structure into lookup dictionaries."""
        bus = self.data.get('business-units', [])

        for bu in bus:
            bu_id = bu.get('id')
            if not bu_id:
                continue

            self.business_units[bu_id] = {
                'cost_centers': set(bu.get('cost-centers', [])),
                'teams': {}
            }

            # Parse teams for this BU
            for team in bu.get('teams', []):
                team_name = team.get('name')
                if team_name:
                    self.business_units[bu_id]['teams'][team_name] = {
                        'namespaces': team.get('namespaces', [])
                    }

        # Parse infrastructure namespaces
        self.infrastructure_namespaces = self.data.get('infrastructure-namespaces', {})

        # Parse valid environments (global)
        self.valid_environments = self.data.get('environments', [])

        logger.info(f"Registry loaded: {len(self.business_units)} business units, "
                    f"{len(self.infrastructure_namespaces)} infrastructure namespaces, "
                    f"{len(self.valid_environments)} environments")

    def validate_business_unit(self, bu: str) -> bool:
        """Check if business unit exists in registry."""
        return bu in self.business_units

    def validate_cost_center(self, bu: str, cost_center: str) -> bool:
        """Check if cost center is valid for the given business unit."""
        if bu not in self.business_units:
            return False
        return cost_center in self.business_units[bu]['cost_centers']

    def validate_team(self, bu: str, team: str) -> bool:
        """Check if team is valid for the given business unit."""
        if bu not in self.business_units:
            return False
        return team in self.business_units[bu]['teams']

    def validate_environment(self, env: str) -> bool:
        """Check if environment is valid."""
        if self.valid_environments:
            return env in self.valid_environments
        # Fallback if no environments defined in registry
        return True

    def get_valid_business_units(self) -> List[str]:
        """Return list of valid business unit IDs."""
        return list(self.business_units.keys())

    def get_valid_cost_centers(self, bu: str) -> List[str]:
        """Return list of valid cost centers for a business unit."""
        if bu not in self.business_units:
            return []
        return list(self.business_units[bu]['cost_centers'])

    def get_valid_teams(self, bu: str) -> List[str]:
        """Return list of valid teams for a business unit."""
        if bu not in self.business_units:
            return []
        return list(self.business_units[bu]['teams'].keys())

    @staticmethod
    def from_configmap(configmap_data: str) -> 'Registry':
        """
        Create Registry from ConfigMap data field.

        Args:
            configmap_data: YAML string from ConfigMap data field

        Returns:
            Registry instance
        """
        registry_dict = yaml.safe_load(configmap_data)
        return Registry(registry_dict)


def load_registry_from_k8s(k8s_client, configmap_name: str, namespace: str) -> Optional[Registry]:
    """
    Load registry from a Kubernetes ConfigMap.

    Args:
        k8s_client: Kubernetes API client
        configmap_name: Name of the ConfigMap
        namespace: Namespace of the ConfigMap

    Returns:
        Registry instance or None if not found
    """
    try:
        from kubernetes import client

        v1 = client.CoreV1Api(k8s_client)
        configmap = v1.read_namespaced_config_map(
            name=configmap_name,
            namespace=namespace
        )

        # ConfigMap should have a 'registry.yaml' key with the data
        registry_yaml = configmap.data.get('registry.yaml')
        if not registry_yaml:
            logger.error(f"ConfigMap {namespace}/{configmap_name} missing 'registry.yaml' key")
            return None

        return Registry.from_configmap(registry_yaml)

    except Exception as e:
        logger.error(f"Failed to load registry from ConfigMap {namespace}/{configmap_name}: {e}")
        return None
