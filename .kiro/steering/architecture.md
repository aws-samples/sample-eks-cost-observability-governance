# Architecture

## High-Level Design

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│   AWS Athena    │◄────────│  Cost Operator   │────────►│   Kubernetes    │
│   (CUR 2.0)    │  Query   │  (Kopf-based)    │  Scan   │   API Server    │
└─────────────────┘         └──────────────────┘         └─────────────────┘
                                     │
                                     ▼
                            ┌──────────────────┐
                            │   Prometheus     │
                            │   (15 metrics)   │
                            └──────────────────┘
```

## Core Components

### Operator (Kopf Handlers)
- Listens for CostGovernance CRD create/update/delete events
- Manages periodic timers for cost collection and compliance scanning
- Coordinates all other components

### Cost Collector
- Queries AWS Athena against CUR 2.0 tables
- Calculates cluster-level, namespace-level, and team-level costs
- Separates application costs from infrastructure costs
- Computes attribution rate (tagged vs untagged)

### Compliance Scanner
- Enumerates pods across all namespaces via Kubernetes API
- Validates required labels are present
- Validates label values against approved registry (ConfigMap-based)
- Produces ViolationReport CRDs and Kubernetes Events

### Metrics Exporter
- Exposes 15 Prometheus metrics at `/metrics` on port 8000
- Updates gauges/counters after each cost collection and compliance scan
- Categories: cost (7), compliance (7), performance (2), info (1)

### CRD Status Manager
- Updates CostGovernance resource `.status` with latest cost and compliance data
- Creates and manages ViolationReport resources (with 7-report retention)

## Custom Resource Definitions

### CostGovernance
- API Group: `cost-governance.io/v1alpha1`
- Defines policy: required labels, allowed values, scan intervals, enforcement mode
- Status holds: cost data, compliance stats, last collection/scan times

### ViolationReport
- API Group: `cost-governance.io/v1alpha1`
- Created after each compliance scan that finds violations
- Contains: scan summary, violation list (per-pod), violation summary (aggregated)
- Auto-pruned to keep most recent 7 reports

## Infrastructure Categories

When separating app costs from infrastructure, components are categorized:

| Category | Examples |
|----------|----------|
| platform | CoreDNS, kube-proxy, metrics-server |
| operations | Karpenter, EBS CSI, Pod Identity Agent |
| observability | Prometheus, Grafana, Node Exporter |
| governance | Cost Governance Operator itself |

## Data Flow

1. **Hourly**: Cost Collector queries Athena → updates CostGovernance status → updates Prometheus metrics
2. **Every 5 min**: Compliance Scanner lists pods → validates labels → creates ViolationReport → emits Events → updates metrics
3. **Every 30s**: Prometheus scrapes `/metrics` endpoint
4. **On CRD change**: Kopf handler triggers immediate collection/scan cycle

## Key Design Decisions

- **Kopf over Go operator-sdk**: Python chosen for rapid development and Athena/boto3 integration
- **CRD-based config**: Governance policies are Kubernetes-native, versionable, and auditable
- **ViolationReports as CRDs**: Provides kubectl-queryable audit trail without external storage
- **Prometheus metrics**: Standard observability pattern, integrates with existing monitoring stacks
- **EKS Pod Identity**: Modern, secure IAM authentication without long-lived credentials
