# Cost Governance Operator — Detailed Guide

This document covers operational details for the Cost Governance Operator: metrics, cost attribution, violation reports, configuration, Grafana dashboards, troubleshooting, and advanced usage.

For introduction, installation, and quick start, see [README.md](./README.md).

---

## Table of Contents

- [Metrics & Observability](#metrics--observability)
- [Cost Attribution](#cost-attribution)
- [Violation Reports](#violation-reports)
- [Configuration & Customization](#configuration--customization)
- [Grafana Dashboard](#grafana-dashboard)
- [Troubleshooting](#troubleshooting)
- [Advanced Usage](#advanced-usage)
- [Cleanup](#cleanup)
- [References](#references)

---

## Metrics & Observability

The operator exposes **15 Prometheus metrics** at `http://<service>:8000/metrics`.

For complete metrics documentation, see: [`PROMETHEUS-METRICS.md`](./src/cost_governance_operator/PROMETHEUS-METRICS.md)

### Metrics Summary

#### Cost Metrics (7 metrics)

| Metric | Type | Description |
|--------|------|-------------|
| `cost_governance_total_cost_usd` | Gauge | Total EKS cluster cost in USD |
| `cost_governance_attribution_rate` | Gauge | % of costs attributed to teams (0-100) |
| `cost_governance_tagged_cost_usd` | Gauge | Cost properly attributed with labels |
| `cost_governance_untagged_cost_usd` | Gauge | Cost not attributed (missing labels) |
| `cost_governance_namespace_cost_usd` | Gauge | Cost breakdown by namespace |
| `cost_governance_team_cost_usd` | Gauge | Cost breakdown by team |
| `cost_governance_pod_count` | Gauge | Total pods with cost data |

#### Compliance Metrics (7 metrics)

| Metric | Type | Description |
|--------|------|-------------|
| `cost_governance_compliance_rate` | Gauge | Overall compliance rate % (0-100) |
| `cost_governance_total_pods` | Gauge | Total pods scanned |
| `cost_governance_compliant_pods` | Gauge | Number of compliant pods |
| `cost_governance_violating_pods` | Gauge | Number of pods with violations |
| `cost_governance_violations_by_type` | Gauge | Violations by type (MissingLabel, InvalidValue) |
| `cost_governance_violations_by_namespace` | Gauge | Violations per namespace |
| `cost_governance_violations_by_label` | Gauge | Violations per label name |

#### Performance Metrics (2 metrics)

| Metric | Type | Description |
|--------|------|-------------|
| `cost_governance_scan_duration_seconds` | Histogram | Compliance scan duration (with percentiles) |
| `cost_governance_scan_errors_total` | Counter | Total scan errors by type |

#### Info Metric (1 metric)

| Metric | Type | Description |
|--------|------|-------------|
| `cost_governance_operator_info` | Gauge | Operator version and phase |

### Example Queries

**Total cluster cost:**
```promql
cost_governance_total_cost_usd
```

**Top 5 expensive namespaces:**
```promql
topk(5, cost_governance_namespace_cost_usd)
```

**Compliance rate over time:**
```promql
cost_governance_compliance_rate[1h]
```

**Most commonly missing label:**
```promql
topk(1, cost_governance_violations_by_label)
```

---

## Cost Attribution

The operator collects cost data **every hour** from AWS Athena and stores it in the `CostGovernance` resource status.

### Collection Schedule

- **Cost collection:** Every 60 minutes (configurable via `spec.collectionSchedule`)
- **Compliance scanning:** Every 5 minutes (configurable via `spec.complianceScanInterval`)
- **Metrics scrape:** Every 30 seconds (Prometheus ServiceMonitor default)

### Attribution Dimensions

The operator tracks costs across **10 dimensions** based on Kubernetes labels:

| Dimension | Kubernetes Label | Example Value |
|-----------|------------------|---------------|
| Team | `team` | `platform-team` |
| Business Unit | `business-unit` | `engineering` |
| Cost Center | `cost-center` | `CC-1234` |
| Application | `application` | `api-gateway` |
| Environment | `environment` | `production` |
| Owner | `owner` | `john.doe@company.com` |
| Project | `project` | `project-alpha` |
| Product | `product` | `mobile-app` |
| Service | `service` | `authentication` |
| Workload | `app.kubernetes.io/name` | `nginx` |

### Cost Breakdown Structure

The operator provides cost data in three levels:

#### 1. Cluster-Level Totals

```bash
kubectl get cg default-governance -n cost-governance-system -o jsonpath='{.status.costData}' | jq '{totalCost, taggedCost, untaggedCost, attributionRate}'
```

#### 2. Namespace-Level Costs

```bash
kubectl get cg default-governance -n cost-governance-system \
  -o jsonpath='{.status.costData.namespaces}' | jq .
```

#### 3. Cluster Infrastructure Breakdown

The operator separates **application costs** from **infrastructure costs** and categorizes infrastructure by purpose:

```bash
kubectl get cg default-governance -n cost-governance-system \
  -o jsonpath='{.status.costData.clusterCostBreakdown}' | jq .
```

### Infrastructure Categories

| Category | Purpose | Example Components |
|----------|---------|-------------------|
| **platform** | Core Kubernetes services | CoreDNS, kube-proxy, metrics-server |
| **operations** | Node/cluster operations | Karpenter, EBS CSI driver, Pod Identity Agent |
| **observability** | Monitoring and logging | Prometheus, Grafana, Node Exporter, Alertmanager |
| **governance** | Cost and policy enforcement | Cost Governance Operator |

### Team-Level Cost Attribution

For pods with proper team labels:

```bash
kubectl get cg default-governance -n cost-governance-system \
  -o jsonpath='{.status.costData.teams}' | jq .
```

### Trigger Cost Collection Manually

```bash
kubectl annotate cg default-governance -n cost-governance-system \
  cost-governance.io/trigger-cost-collection="$(date +%s)" --overwrite
```

---

## Violation Reports

Every compliance scan that finds non-compliant pods creates a `ViolationReport` custom resource. These reports are persistent, queryable, and give you a detailed audit trail of compliance state over time.

### List Violation Reports

```bash
kubectl get violationreports -n cost-governance-system
```

Reports are named `{governance-name}-{YYYYMMDD-HHMMSS}` and created every 5 minutes. The operator automatically retains the most recent 7 reports and cleans up older ones.

### Inspect a Violation Report

```bash
kubectl get violationreport <report-name> -n cost-governance-system -o yaml
```

Each report includes:
- **Scan summary** — total pods, compliant pods, violating pods, compliance rate
- **Violation list** — every non-compliant pod with its namespace, current labels, and specific violations
- **Violation summary** — counts broken down by type (`MissingLabel`, `InvalidValue`), by namespace, and by label

### Query Violations

**Get the violation list from the latest report:**
```bash
kubectl get vr -n cost-governance-system --sort-by=.spec.scanTime -o name | tail -1 | \
  xargs kubectl get -n cost-governance-system -o json | jq '.spec.violations'
```

**Get the violation summary (counts by type, namespace, label):**
```bash
kubectl get vr -n cost-governance-system --sort-by=.spec.scanTime -o name | tail -1 | \
  xargs kubectl get -n cost-governance-system -o json | jq '.spec.violationSummary'
```

### Kubernetes Events

The operator creates Kubernetes Events on each non-compliant pod (visible in `kubectl describe pod`):

```bash
kubectl get events --all-namespaces --field-selector reason=ComplianceViolation
```

Events have a default 1-hour TTL, so ViolationReports are the durable record.

---

## Configuration & Customization

### CostGovernance CRD Spec

```yaml
apiVersion: cost-governance.io/v1alpha1
kind: CostGovernance
metadata:
  name: default-governance
  namespace: cost-governance-system
spec:
  enforcementMode: audit  # or "enforce"
  requiredLabels:
  - cost-center
  - business-unit
  - team
  - application
  - environment
  labelValidation:
    team:
      allowedValues: [platform-team, data-team, mobile-team]
    business-unit:
      allowedValues: [engineering, product, sales]
    environment:
      allowedValues: [production, staging, development]
  collectionSchedule: "0 * * * *"  # Every hour
  complianceScanInterval: 300  # Every 5 minutes
  resourceThresholds:
    cpu: "4"
    memory: "16Gi"
    requiresGpuApproval: true
```

### Spec Fields Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enforcementMode` | string | `audit` | `audit` (log only) or `enforce` (block non-compliant pods) |
| `requiredLabels` | array | `[cost-center, business-unit, team, application, environment]` | Labels required on all pods |
| `labelValidation.<label>.allowedValues` | array | `[]` | Allowed values for specific labels |
| `collectionSchedule` | string | `"0 * * * *"` | Cron schedule for cost collection |
| `complianceScanInterval` | int | `300` | Seconds between compliance scans |
| `resourceThresholds.cpu` | string | `"4"` | CPU threshold for approval |
| `resourceThresholds.memory` | string | `"16Gi"` | Memory threshold for approval |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EKS_CLUSTER_NAME` | Required | Name of your EKS cluster |
| `ATHENA_DATABASE` | `billingdata` | Athena database name for CUR data |
| `ATHENA_TABLE` | `data` | Athena table name |
| `ATHENA_S3_OUTPUT` | Required | S3 bucket for Athena query results |
| `AWS_REGION` | `us-east-1` | AWS region for Athena queries |
| `COST_LOOKBACK_DAYS` | `7` | Days of cost data to query |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

### Customize Required Labels

```bash
kubectl edit cg default-governance -n cost-governance-system
```

### Change Collection Frequency

```yaml
spec:
  collectionSchedule: "*/30 * * * *"  # Every 30 minutes
  complianceScanInterval: 900  # Every 15 minutes
```

### Customize Infrastructure Categories

Edit `src/cost_governance_operator/utils/cluster_infrastructure_config.py`:

```python
NAMESPACE_CATEGORIES = {
    "kube-system": "platform",
    "monitoring": "observability",
    "karpenter": "operations",
    "cost-governance-system": "governance",
    "logging": "observability",  # Add new
}
```

After changes: `make push && make restart`

---

## Grafana Dashboard

A pre-built Grafana dashboard is provided with **17 panels** covering all cost, compliance, and performance metrics.

### Import Dashboard

1. Port-forward to Grafana:
   ```bash
   make grafana-connect
   ```

2. Import dashboard:
   - Click **"+"** (Create) → **"Import"**
   - Upload: `src/cost_governance_operator/grafana-dashboard/cost-governance-dashboard.json`
   - Select **Prometheus** datasource

For complete dashboard documentation, see: [`grafana-dashboard/README.md`](./src/cost_governance_operator/grafana-dashboard/README.md)

---

## Troubleshooting

### Operator Pod Not Starting

```bash
kubectl get pods -n cost-governance-system
kubectl describe pod -n cost-governance-system -l app=cost-governance-operator
```

Common issues: image pull failure, CrashLoopBackOff (check logs).

### Cost Data Not Collected

1. Check logs: `kubectl logs -n cost-governance-system -l app=cost-governance-operator | grep "Cost collection"`
2. Check IAM: `aws eks list-pod-identity-associations --cluster-name <cluster>`
3. Check Athena database exists
4. Trigger manually: `kubectl annotate cg default-governance -n cost-governance-system cost-governance.io/trigger-cost-collection="$(date +%s)" --overwrite`

### Prometheus Metrics Not Appearing

1. Check metrics endpoint: `make operator-connect` then `curl http://localhost:8000/metrics`
2. Check ServiceMonitor: `kubectl get servicemonitor -n monitoring cost-governance-operator`
3. Check Prometheus targets at http://localhost:9090/targets

### Compliance Rate is 0%

1. Check scan ran: `grep "Compliance scan complete" in logs`
2. Trigger manual scan: `kubectl annotate cg default-governance -n cost-governance-system cost-governance.io/trigger-scan="$(date +%s)" --overwrite`

### Athena Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `SYNTAX_ERROR` | Invalid SQL | Check `ATHENA_DATABASE` env var |
| `S3 bucket does not exist` | Bad `ATHENA_S3_OUTPUT` | Verify bucket exists |
| `Access Denied` | IAM missing permissions | Check role has athena:*, s3:*, glue:* |

---

## Advanced Usage

### Multiple Governance Policies

```bash
# Production (strict)
kubectl apply -f - <<EOF
apiVersion: cost-governance.io/v1alpha1
kind: CostGovernance
metadata:
  name: production-governance
  namespace: cost-governance-system
spec:
  enforcementMode: enforce
  requiredLabels: [cost-center, business-unit, team, application, environment, owner]
  complianceScanInterval: 300
EOF
```

### Export Cost Data to CSV

```bash
kubectl get cg default-governance -n cost-governance-system \
  -o jsonpath='{.status.costData.namespaces}' | \
  jq -r '.[] | [.namespace, .totalCost, .podCount] | @csv' > namespace-costs.csv
```

### Alerting on Cost Thresholds

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: cost-governance-alerts
  namespace: monitoring
spec:
  groups:
  - name: cost-governance
    interval: 5m
    rules:
    - alert: HighClusterCost
      expr: cost_governance_total_cost_usd > 100
      for: 1h
    - alert: LowComplianceRate
      expr: cost_governance_compliance_rate < 50
      for: 15m
```

### CI/CD Integration

```bash
#!/bin/bash
COMPLIANCE=$(kubectl get cg default-governance -n cost-governance-system \
  -o jsonpath='{.status.compliance.complianceRate}')

if (( $(echo "$COMPLIANCE < 80" | bc -l) )); then
  echo "ERROR: Compliance rate is ${COMPLIANCE}%, must be >= 80%"
  exit 1
fi
```

---

## Cleanup

### Remove Operator

```bash
make undeploy
```

### Remove AWS Resources

```bash
# Delete Pod Identity association
ASSOCIATION_ID=$(aws eks list-pod-identity-associations \
  --cluster-name <cluster> --region us-east-1 \
  --query "associations[?serviceAccount=='cost-governance-operator'].associationId" \
  --output text)
aws eks delete-pod-identity-association --cluster-name <cluster> --association-id $ASSOCIATION_ID --region us-east-1

# Delete IAM role
aws iam delete-role-policy --role-name CostGovernanceOperatorRole --policy-name AthenaAccess
aws iam delete-role --role-name CostGovernanceOperatorRole
```

---

## References

- [AWS Split-Cost Allocation](https://aws.amazon.com/blogs/aws-cloud-financial-management/using-kubernetes-labels-to-split-and-track-application-costs-on-amazon-eks-2/)
- [EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html)
- [AWS Cost and Usage Reports](https://docs.aws.amazon.com/cur/latest/userguide/what-is-cur.html)
- [Kopf Framework](https://kopf.readthedocs.io/)
- [Prometheus Operator](https://prometheus-operator.dev/)
- [Karpenter](https://karpenter.sh/)
