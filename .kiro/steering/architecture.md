# Architecture

## High-Level Design

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│   AWS Athena    │◄────────│  Cost Operator   │◄───────►│   Kubernetes    │
│   (CUR 2.0)    │  Query   │  (Kopf-based)    │  Scan   │   API Server    │
└─────────────────┘         └──────────────────┘  +      └─────────────────┘
                                     │             Admit          │
                                     ▼          (webhook :9443)   │
                            ┌──────────────────┐                  ▼
                            │   Prometheus     │        pods rejected in
                            │  (18 metrics)    │        enforce mode
                            └──────────────────┘
```

## Core Components

### Operator (Kopf Handlers) — `main.py`
- Listens for CostGovernance CRD create/update/delete events (update/delete currently only log)
- Manages periodic timers: compliance scan every 300s, cost collection every 3600s (60s initial delay)
- Starts the Prometheus HTTP server on port 8000 and exposes liveness/readiness probes
- Coordinates all other components and writes CRD `.status`

### Cost Collector — `collectors/athena_collector.py` (`AthenaCollector`)
- Queries AWS Athena against CUR 2.0 tables
- Calculates cluster-level, namespace-level, and team-level costs
- Separates application costs from infrastructure costs
- Computes attribution rate (tagged vs untagged) and namespace cost utilization

### Compliance Validator — `validators/validators.py` (`Validator`)
- Enumerates pods across all namespaces via Kubernetes API (excludes kube-system, kube-public, kube-node-lease, gatekeeper-system)
- Validates required labels are present and non-empty
- Validates label values against the approved registry (business-unit, cost-center, team, environment)
- Validates resource requests are present and within CPU/memory thresholds
- Produces a ComplianceSummary of per-pod results

### Violation Reporter — `reporters/violation_reporter.py` (`ViolationReporter`)
- Creates ViolationReport CRDs from scan results
- Prunes old reports, keeping the most recent 7

### Metrics Exporter — `exporters/prometheus_exporter.py` (`PrometheusExporter`)
- Exposes 18 Prometheus metric instruments at `/metrics` on port 8000
- Instruments: 15 Gauges (compliance + cost), 1 Histogram (scan duration), 1 Counter (scan errors), 1 Info (operator version)
- Updates metrics after each cost collection and compliance scan

### Admission Webhook (enforce mode) — `main.py` (`enforce_pod_labels`, `ServiceWebhookServer`)
- `@kopf.on.validate` handler on `pods`/CREATE; rejects pods missing required labels
  when the active policy is `enforce`, warns (non-blocking) when `audit`
- Exempts system + operator namespaces (kube-system, kube-public, kube-node-lease, cost-governance-system)
- `ServiceWebhookServer` serves HTTPS on port 9443 using a cert mounted from a Secret
  (`/etc/webhook/certs`); Kopf does NOT manage the webhook config (`settings.admission.managed = None`)
- Reads the enforcement policy from an in-memory cache populated by the CostGovernance
  create/update/`resume` handlers, so no API call is made per admission request
- Registered without `ignore_failures` (that option would suppress denials); fail-open
  safety comes from the static config's `failurePolicy: Ignore`

### Static webhook config — `k8s_configs/webhook/`
- `validating-webhook-configuration.yaml`: static ValidatingWebhookConfiguration
  (`cost-governance.io`) applied once, pointing at the operator Service on 9443,
  path `/enforce-pod-labels`, `failurePolicy: Ignore`, namespace exclusions
- `gen-certs.sh`: generates a self-signed CA + serving cert (SANs for the Service DNS),
  creates the cert Secret, injects the CA bundle into the config, and applies it

## Custom Resource Definitions

### CostGovernance
- API Group / Version: `cost-governance.io` / `v1alpha1`, scope: Namespaced (shortName `cg`)
- Defines policy: `requiredLabels`, `resourceThresholds` (cpu/memory/requiresGpuApproval), `registryConfigMap`, `costCollection` (Athena config), `collectionSchedule`, and `enforcementMode`
- `enforcementMode` (`audit` | `enforce`, default `audit`): in `enforce`, the admission webhook rejects pods missing required labels at creation; in `audit`, non-compliance is reported only
- Status holds: `complianceRate`, `totalPods`, `violatingPods`, `conditions`, `costData`, `lastCollectionTime`

### ViolationReport
- API Group / Version: `cost-governance.io` / `v1alpha1`
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

1. **Hourly** (3600s timer, 60s initial delay): Cost Collector queries Athena → updates CostGovernance status → updates Prometheus metrics
2. **Every 5 min** (300s timer): Compliance Validator lists pods → validates labels + resources → creates ViolationReport (when violations exist) → emits Kubernetes Events → updates metrics
3. **Every 30s**: Prometheus scrapes `/metrics` endpoint
4. **On CRD create/update/resume**: caches the policy (enforcement mode + required labels); create triggers an immediate compliance scan
5. **On pod CREATE (enforce mode)**: API server calls the admission webhook → operator checks required labels → rejects the pod if any are missing (audit mode warns instead)

## Key Design Decisions

- **Kopf over Go operator-sdk**: Python chosen for rapid development and Athena/boto3 integration
- **CRD-based config**: Governance policies are Kubernetes-native, versionable, and auditable
- **ViolationReports as CRDs**: Provides kubectl-queryable audit trail without external storage
- **Prometheus metrics**: Standard observability pattern, integrates with existing monitoring stacks
- **EKS Pod Identity**: Modern, secure IAM authentication without long-lived credentials
- **Static webhook config over Kopf-managed**: Kopf-managed ValidatingWebhookConfigurations proved fragile on EKS (empty/wiped/rotated configs across operator restarts). A static config we own plus a fixed self-signed CA (mounted from a Secret) is stable and restart-proof — the standard way to run admission webhooks without cert-manager.
- **Fail-open enforcement**: the webhook uses `failurePolicy: Ignore` so an unreachable or down operator never blocks pod creation cluster-wide.
