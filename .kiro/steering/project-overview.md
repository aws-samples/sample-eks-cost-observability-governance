# Project Overview

## What This Project Is

This is the **EKS Cost Governance Operator** — a Kubernetes operator that provides cost observability, attribution, and governance for Amazon EKS clusters using AWS Split-Cost Allocation Data (CUR 2.0).

The operator runs alongside workloads on EKS and:
- Collects pod-level cost data from AWS Athena (CUR 2.0) every hour
- Continuously validates pods have required cost attribution labels (every 5 minutes)
- Checks label values against an approved registry (business-unit, cost-center, team, environment)
- Validates pod resource requests are present and within CPU/memory thresholds
- Reports violations via ViolationReport CRDs and Prometheus metrics
- Separates application spend from cluster infrastructure overhead
- Optionally blocks non-compliant pods at creation via an admission webhook (enforce mode)

The operator supports two modes, set per CostGovernance resource via `spec.enforcementMode`:
- **audit** (default): detects and reports non-compliant pods after they are running (periodic scan + ViolationReports + metrics).
- **enforce**: additionally rejects pods missing required labels at creation time via a validating admission webhook.

## Technology Stack

- **Language:** Python 3.14
- **Package Manager:** uv (with uv.lock)
- **Kubernetes Framework:** Kopf (Kubernetes Operator Pythonic Framework)
- **AWS Integration:** Athena queries via boto3, EKS Pod Identity for IAM auth
- **Observability:** Prometheus client (18 metric instruments exposed at /metrics on port 8000)
- **Dashboards:** Grafana (17-panel pre-built dashboard)
- **Linting:** Ruff (line-length 120, rules: E, F, I, W)
- **Testing:** pytest with pytest-asyncio, pytest-cov (80% coverage threshold)
- **Security Scanning:** Bandit, gitleaks, ProtoShield

## Project Status

The operator is implemented (labelled "Phase 3: Cost Collection + Violation Reporting" in the code). Cost collection, compliance scanning, violation reporting, and Prometheus metrics are all working. Actual source layout:

```
src/cost_governance_operator/
  main.py            # Kopf handlers, entrypoint, Prometheus server startup
  config.py          # Environment-variable-based configuration
  collectors/        # AthenaCollector - CUR 2.0 query logic, cost breakdown
  validators/        # Validator - pod scanning, label + resource validation
  reporters/         # ViolationReporter - ViolationReport CRDs, cleanup/retention
  exporters/         # PrometheusExporter - metric definitions and updates
  models/            # cost_data - cost/attribution data models
  utils/             # Athena helpers, registry loading, cluster infra config
  scripts/           # Standalone Athena/CUR exploration scripts
  tests/             # Test package
  k8s_configs/       # CRDs, deployment manifests, IAM, examples, monitoring, webhook
  grafana-dashboard/ # Pre-built Grafana dashboard
```

### Enforce mode (admission webhook)

Enforce mode is implemented as a validating admission webhook (`@kopf.on.validate` on
`pods`/CREATE) that rejects pods missing required labels when a CostGovernance
resource has `spec.enforcementMode: enforce`.

Key design points (see `k8s_configs/webhook/` and Architecture):
- The webhook uses a **static ValidatingWebhookConfiguration** that we own and apply
  once — it is NOT managed by Kopf. This avoids the churn (empty/wiped/rotated
  configs on restart) seen with Kopf-managed configs on EKS.
- TLS uses a **self-signed CA + serving cert generated once** (`gen-certs.sh`) and
  mounted from a Secret; the same CA is the config's `caBundle`. Nothing rotates on
  restart.
- `failurePolicy: Ignore` (fail-open): if the operator is down/unreachable, pods are
  still admitted, so a broken webhook cannot wedge the cluster.
- The operator populates its policy cache from `@kopf.on.resume` (and the compliance
  timer) so enforcement survives restarts.
- Deploy with `make deploy-enforce-all`; switch a running operator between modes by
  applying the audit vs enforce CostGovernance instance.

### Not yet implemented / limitations

- **Delete handler:** the `delete` handler for CostGovernance only logs; it does not
  clean up beyond dropping the cached policy.
- **Enforcement scope:** the webhook checks label *presence* only, not label *values*
  (value validation against the registry still happens in the periodic audit scan).

## Key Concepts

- **CostGovernance CRD** — Defines governance policies (required labels, resource thresholds, registry ConfigMap reference, cost collection config, enforcement mode). API group `cost-governance.io`, version `v1alpha1`, namespaced.
- **ViolationReport CRD** — Created after each compliance scan that finds violations, with full audit details (pruned to the most recent 7)
- **Split-Cost Allocation** — AWS feature that breaks node costs down to individual pods in CUR
- **Infrastructure Categories** — platform, operations, observability, governance (for cost separation)
- **Attribution Rate** — Percentage of costs properly attributed via labels
