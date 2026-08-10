# Project Overview

## What This Project Is

This is the **EKS Cost Governance Operator** — a Kubernetes operator that provides cost observability, attribution, and governance for Amazon EKS clusters using AWS Split-Cost Allocation Data (CUR 2.0).

The operator runs alongside workloads on EKS and:
- Collects pod-level cost data from AWS Athena (CUR 2.0) every hour
- Continuously validates pods have required cost attribution labels (every 5 minutes)
- Checks label values against an approved registry
- Reports violations via CRDs, Kubernetes Events, and Prometheus metrics
- Separates application spend from cluster infrastructure overhead

## Technology Stack

- **Language:** Python 3.14
- **Package Manager:** uv (with uv.lock)
- **Kubernetes Framework:** Kopf (Kubernetes Operator Pythonic Framework)
- **AWS Integration:** Athena queries via boto3, EKS Pod Identity for IAM auth
- **Observability:** Prometheus client (15 metrics exposed at /metrics)
- **Dashboards:** Grafana (17-panel pre-built dashboard)
- **Linting:** Ruff (line-length 120, rules: E, F, I, W)
- **Testing:** pytest with pytest-asyncio, pytest-cov (80% coverage threshold)
- **Security Scanning:** Bandit, gitleaks, ProtoShield

## Project Status

This is a skeleton/template project with full documentation and tooling configuration in place. The implementation code is yet to be written. Expected source layout:

```
src/
  operator/          # Kopf handlers, main entrypoint
  cost_collector/    # Athena query logic, cost breakdown
  compliance/        # Pod scanning, label validation
  metrics/           # Prometheus metric definitions and updates
  utils/             # Cluster infrastructure config, helpers
  crds/              # CRD definitions and status management
```

## Key Concepts

- **CostGovernance CRD** — Defines governance policies (required labels, allowed values, schedules)
- **ViolationReport CRD** — Created after each compliance scan with full audit details
- **Split-Cost Allocation** — AWS feature that breaks node costs down to individual pods in CUR
- **Infrastructure Categories** — platform, operations, observability, governance (for cost separation)
- **Attribution Rate** — Percentage of costs properly attributed via labels
