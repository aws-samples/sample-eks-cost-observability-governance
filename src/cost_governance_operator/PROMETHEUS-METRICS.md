# Prometheus Metrics Reference

The Cost Governance Operator exposes metrics at `http://<service>:8000/metrics` for Prometheus scraping.

---

## How to Discover Metrics

### Method 1: Direct Endpoint Query
```bash
# Port-forward to operator
kubectl port-forward -n cost-governance-system svc/cost-governance-operator 8000:8000

# List all cost governance metrics
curl http://localhost:8000/metrics | grep "^cost_governance"
```

### Method 2: Prometheus UI
1. Open Prometheus: http://localhost:9090
2. Click **Graph** tab
3. Use metrics dropdown or type `cost_governance` to filter

### Method 3: Query All Metrics
```promql
{__name__=~"cost_governance.*"}
```

---

## Available Metrics

### Cost Metrics

#### `cost_governance_total_cost_usd`
**Type:** Gauge  
**Description:** Total EKS cluster cost in USD for the reporting period  
**Labels:**
- `governance_name` - CostGovernance resource name
- `governance_namespace` - CostGovernance namespace
- `cluster` - EKS cluster name

**Example Query:**
```promql
cost_governance_total_cost_usd{cluster="cost-demo-eks-cluster"}
```

**Example Value:** `10.87`

---

#### `cost_governance_attribution_rate`
**Type:** Gauge  
**Description:** Percentage of costs that can be attributed to specific teams/cost centers (0-100)  
**Labels:**
- `governance_name`
- `governance_namespace`
- `cluster`

**Example Query:**
```promql
cost_governance_attribution_rate
```

**Example Value:** `4.98` (4.98% of costs are properly tagged)

---

#### `cost_governance_tagged_cost_usd`
**Type:** Gauge  
**Description:** Cost properly attributed with cost governance labels in USD  
**Labels:**
- `governance_name`
- `governance_namespace`
- `cluster`

**Example Query:**
```promql
cost_governance_tagged_cost_usd
```

**Example Value:** `0.54` ($0.54 can be charged back to teams)

---

#### `cost_governance_untagged_cost_usd`
**Type:** Gauge  
**Description:** Cost not attributed due to missing tags in USD  
**Labels:**
- `governance_name`
- `governance_namespace`
- `cluster`

**Example Query:**
```promql
cost_governance_untagged_cost_usd
```

**Example Value:** `10.33` ($10.33 is untagged infrastructure or untagged apps)

---

#### `cost_governance_namespace_cost_usd`
**Type:** Gauge  
**Description:** Cost breakdown by Kubernetes namespace in USD  
**Labels:**
- `governance_name`
- `governance_namespace`
- `cluster`
- `pod_namespace` - The namespace being measured

**Example Queries:**
```promql
# All namespace costs
cost_governance_namespace_cost_usd

# Top 5 most expensive namespaces
topk(5, cost_governance_namespace_cost_usd)

# Cost of specific namespace
cost_governance_namespace_cost_usd{pod_namespace="karpenter"}

# Namespaces costing more than $1
cost_governance_namespace_cost_usd > 1
```

**Example Values:**
- `karpenter: $6.36`
- `kube-system: $2.28`
- `test-apps: $0.80`
- `monitoring: $0.65`

---

#### `cost_governance_team_cost_usd`
**Type:** Gauge  
**Description:** Cost breakdown by team in USD (only for properly tagged pods)  
**Labels:**
- `governance_name`
- `governance_namespace`
- `cluster`
- `team` - Team name from pod labels
- `business_unit` - Business unit the team belongs to

**Example Query:**
```promql
# Costs by team
cost_governance_team_cost_usd

# Total cost for engineering teams
sum(cost_governance_team_cost_usd{business_unit="engineering"})
```

**Note:** Currently empty if pods don't have proper team tags.

---

### Compliance Metrics

#### `cost_governance_compliance_rate`
**Type:** Gauge  
**Description:** Overall compliance rate percentage (0-100)  
**Labels:**
- `governance_name`
- `governance_namespace`

**Example Query:**
```promql
cost_governance_compliance_rate
```

**Example Value:** `36.67` (36.67% of pods are compliant)

---

#### `cost_governance_total_pods`
**Type:** Gauge  
**Description:** Total number of pods scanned  
**Labels:**
- `governance_name`
- `governance_namespace`

**Example Query:**
```promql
cost_governance_total_pods
```

**Example Value:** `30`

---

#### `cost_governance_compliant_pods`
**Type:** Gauge  
**Description:** Number of pods meeting all governance requirements  
**Labels:**
- `governance_name`
- `governance_namespace`

**Example Query:**
```promql
cost_governance_compliant_pods
```

**Example Value:** `11`

---

#### `cost_governance_violating_pods`
**Type:** Gauge  
**Description:** Number of pods with governance violations  
**Labels:**
- `governance_name`
- `governance_namespace`

**Example Query:**
```promql
cost_governance_violating_pods
```

**Example Value:** `19`

---

#### `cost_governance_violations_by_type`
**Type:** Gauge  
**Description:** Breakdown of violations by type  
**Labels:**
- `governance_name`
- `governance_namespace`
- `violation_type` - Type of violation (e.g., "MissingLabel", "InvalidValue")

**Example Queries:**
```promql
# All violation types
cost_governance_violations_by_type

# Only missing label violations
cost_governance_violations_by_type{violation_type="MissingLabel"}
```

**Example Values:**
- `MissingLabel: 75`
- `InvalidValue: 7`

---

#### `cost_governance_violations_by_namespace`
**Type:** Gauge  
**Description:** Number of violations per namespace  
**Labels:**
- `governance_name`
- `governance_namespace`
- `pod_namespace` - Namespace containing violations

**Example Queries:**
```promql
# Violations by namespace
cost_governance_violations_by_namespace

# Top 3 namespaces with most violations
topk(3, cost_governance_violations_by_namespace)
```

**Example Values:**
- `monitoring: 10`
- `test-compliance: 4`
- `default: 3`
- `karpenter: 2`

---

#### `cost_governance_violations_by_label`
**Type:** Gauge  
**Description:** Number of violations per label name  
**Labels:**
- `governance_name`
- `governance_namespace`
- `label` - The label that's missing or invalid

**Example Queries:**
```promql
# Which labels are most often missing?
cost_governance_violations_by_label

# How many pods are missing cost-center?
cost_governance_violations_by_label{label="cost-center"}
```

**Example Values:**
- `cost-center: 17`
- `team: 17`
- `environment: 17`
- `business-unit: 16`
- `application: 15`

---

### Performance Metrics

#### `cost_governance_scan_duration_seconds`
**Type:** Histogram  
**Description:** Compliance scan duration in seconds (with buckets)  
**Labels:**
- `governance_name`
- `governance_namespace`

**Example Queries:**
```promql
# Average scan duration (last 5 minutes)
rate(cost_governance_scan_duration_seconds_sum[5m]) / rate(cost_governance_scan_duration_seconds_count[5m])

# 95th percentile scan time
histogram_quantile(0.95, rate(cost_governance_scan_duration_seconds_bucket[5m]))

# Total scans completed
cost_governance_scan_duration_seconds_count
```

**Buckets:** 0.005s, 0.01s, 0.025s, 0.05s, 0.075s, 0.1s, 0.25s, 0.5s, 0.75s, 1s, 2.5s, 5s, 7.5s, 10s

---

#### `cost_governance_scan_errors_total`
**Type:** Counter  
**Description:** Total number of scan errors (monotonically increasing)  
**Labels:**
- `governance_name`
- `governance_namespace`
- `error_type` - Type of error (e.g., "registry_load_failed", "k8s_api_error")

**Example Queries:**
```promql
# Total errors
cost_governance_scan_errors_total

# Error rate (errors per second over 5 minutes)
rate(cost_governance_scan_errors_total[5m])

# Errors by type
sum by (error_type) (cost_governance_scan_errors_total)
```

---

### Operator Info Metric

#### `cost_governance_operator_info`
**Type:** Info/Gauge  
**Description:** Static information about the operator  
**Labels:**
- `version` - Operator version
- `phase` - Implementation phase

**Example Query:**
```promql
cost_governance_operator_info
```

**Example Value:** `{version="1.0.0", phase="3"} = 1`

---

## Useful PromQL Queries

### Cost Analysis

```promql
# Total cluster cost trend (7 days)
cost_governance_total_cost_usd[7d]

# Cost growth rate
rate(cost_governance_total_cost_usd[1d])

# Percentage of cost that's attributed
(cost_governance_tagged_cost_usd / cost_governance_total_cost_usd) * 100

# Most expensive namespace
topk(1, cost_governance_namespace_cost_usd)

# Infrastructure vs Application cost (approximate)
# Infrastructure namespaces
sum(cost_governance_namespace_cost_usd{pod_namespace=~"kube-system|monitoring|karpenter|cost-governance-system"})
# Application namespaces
sum(cost_governance_namespace_cost_usd{pod_namespace=~"test-.*|default"})
```

### Compliance Analysis

```promql
# Compliance rate trend
cost_governance_compliance_rate[1h]

# Compliance improvement over 24 hours
delta(cost_governance_compliance_rate[24h])

# Violation rate (percentage)
(cost_governance_violating_pods / cost_governance_total_pods) * 100

# Most problematic namespace
topk(1, cost_governance_violations_by_namespace)

# Most commonly missing label
topk(1, cost_governance_violations_by_label)
```

### Alerting Queries

```promql
# Alert if compliance drops below 50%
cost_governance_compliance_rate < 50

# Alert if total cost exceeds $20
cost_governance_total_cost_usd > 20

# Alert if attribution rate is too low
cost_governance_attribution_rate < 10

# Alert if scan duration exceeds 5 seconds
histogram_quantile(0.95, rate(cost_governance_scan_duration_seconds_bucket[5m])) > 5

# Alert on scan errors
rate(cost_governance_scan_errors_total[5m]) > 0
```

---

## Grafana Dashboard Panels

### Recommended Panels

**1. Total Cost Gauge**
```promql
cost_governance_total_cost_usd
```
Display as: Stat panel with "USD" unit

**2. Cost Trend Graph**
```promql
cost_governance_total_cost_usd
```
Display as: Time series graph (7-day range)

**3. Cost by Namespace Bar Chart**
```promql
cost_governance_namespace_cost_usd
```
Display as: Bar chart, sorted by value

**4. Attribution Rate Gauge**
```promql
cost_governance_attribution_rate
```
Display as: Gauge (0-100 range), with thresholds:
- Red: < 20
- Yellow: 20-60
- Green: > 60

**5. Compliance Rate Gauge**
```promql
cost_governance_compliance_rate
```
Display as: Gauge (0-100 range), with thresholds:
- Red: < 50
- Yellow: 50-80
- Green: > 80

**6. Top 5 Expensive Namespaces Table**
```promql
topk(5, cost_governance_namespace_cost_usd)
```
Display as: Table with columns: Namespace, Cost

**7. Violations by Type Pie Chart**
```promql
cost_governance_violations_by_type
```
Display as: Pie chart

---

## ServiceMonitor Configuration

To enable automatic Prometheus scraping:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: cost-governance-operator
  namespace: monitoring
  labels:
    release: prometheus
spec:
  namespaceSelector:
    matchNames:
    - cost-governance-system
  selector:
    matchLabels:
      app: cost-governance-operator
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
```

---

## Troubleshooting

### Metrics not appearing in Prometheus

1. **Check ServiceMonitor is created:**
```bash
kubectl get servicemonitor -n monitoring
```

2. **Verify labels match Prometheus selector:**
```bash
kubectl get prometheus -n monitoring -o yaml | grep serviceMonitorSelector -A 5
```

3. **Check Prometheus targets:**
- Open Prometheus UI: http://localhost:9090/targets
- Look for `monitoring/cost-governance-operator`
- Should show as "UP" (green)

4. **Test metrics endpoint directly:**
```bash
kubectl run test-curl --rm -it --image=curlimages/curl --restart=Never -- \
  curl http://cost-governance-operator.cost-governance-system.svc:8000/metrics
```

### Metrics showing 0 or no data

- **Cost metrics:** Wait for cost collection to run (every hour, or trigger manually)
- **Compliance metrics:** Wait for compliance scan to run (every 5 minutes)
- **Check operator logs:**
```bash
kubectl logs -n cost-governance-system -l app=cost-governance-operator --tail=50
```

---

## Metric Collection Schedule

- **Compliance scans:** Every 5 minutes
- **Cost collection:** Every 60 minutes (configurable)
- **Metrics scrape:** Every 30 seconds (ServiceMonitor default)

Cost and compliance data is refreshed automatically based on these schedules.
