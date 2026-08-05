# Cost Governance Operator - Grafana Dashboard

Complete Grafana dashboard for visualizing cost and compliance metrics from the Cost Governance Operator.

---

## Dashboard Features

### Cost Metrics (6 Panels)
- **Total Cluster Cost** - Gauge with cost thresholds
- **Cost Attribution Rate** - How much cost can be charged back
- **Tagged vs Untagged Costs** - Pie chart showing attribution
- **Cost Trend** - Historical cost over time
- **Cost by Namespace** - Bar chart of namespace costs
- **Pod Count** - Total pods with cost data

### Compliance Metrics (7 Panels)
- **Compliance Rate** - Overall pod compliance percentage
- **Compliant vs Violating Pods** - Donut chart
- **Violations by Type** - MissingLabel vs InvalidValue
- **Pod Summary** - Total/Compliant/Violating counts
- **Violations by Namespace** - Which namespaces need work
- **Violations by Label** - Which labels are most often missing
- **Compliance Trend** - Historical compliance rate

### Performance Metrics (4 Panels)
- **Scan Duration** - Average and 95th percentile
- **Scan Errors** - Error rate over time
- **Total Scans** - Number of completed scans
- **Operator Version** - Current version info

---

## Installation

### Prerequisites

1. **Prometheus** with ServiceMonitor configured:
```bash
kubectl get servicemonitor -n monitoring cost-governance-operator
```

2. **Grafana** accessible:
```bash
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
```

3. **Metrics flowing** to Prometheus:
```bash
# Check in Prometheus UI (http://localhost:9090)
cost_governance_total_cost_usd
```

---

## Import Methods

### Method 1: Grafana UI (Recommended)

**Step 1: Access Grafana**
```bash
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
```

Open: http://localhost:3000

**Step 2: Get Admin Password**
```bash
# If default password doesn't work (admin/prom-operator):
kubectl get secret -n monitoring prometheus-grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode; echo
```

**Step 3: Import Dashboard**
1. Click **"+"** (Create) in left sidebar
2. Click **"Import"**
3. Click **"Upload JSON file"**
4. Select: `cost-governance-dashboard.json`
5. Click **"Load"**
6. Select **Prometheus** as the data source
7. Click **"Import"**

✅ Dashboard is now available!

### Method 2: Auto-Discovery via ConfigMap

If your Grafana is configured to auto-discover dashboards from ConfigMaps:

```bash
# Create ConfigMap with dashboard JSON
kubectl create configmap cost-governance-dashboard \
  --from-file=cost-governance-dashboard.json=./cost-governance-dashboard.json \
  -n monitoring \
  --dry-run=client -o yaml | \
  kubectl label -f - grafana_dashboard=1 --local --dry-run=client -o yaml | \
  kubectl apply -f -
```

Grafana will automatically discover and import the dashboard.

---

## Dashboard Configuration

### Time Range
- **Default:** Last 24 hours
- **Refresh:** Every 30 seconds

You can adjust these in the dashboard settings (top right, clock icon).

### Prometheus Datasource
The dashboard expects a Prometheus datasource named `prometheus`. 

**To change:**
1. Dashboard Settings (gear icon, top right)
2. Variables tab
3. Add/Edit datasource variable

---

## Panel Descriptions

### Cost Overview Panels

#### Total Cluster Cost
**Query:** `cost_governance_total_cost_usd`

Shows the total EKS cluster cost in USD. Color thresholds:
- Green: < $10
- Yellow: $10-$20
- Orange: $20-$50
- Red: > $50

#### Cost Attribution Rate
**Query:** `cost_governance_attribution_rate`

Percentage of costs that can be attributed to teams. Thresholds:
- Green: > 60% (good)
- Yellow: 20-60% (needs improvement)
- Red: < 20% (poor attribution)

#### Cost Attribution Breakdown
**Queries:**
- `cost_governance_tagged_cost_usd` - Properly attributed costs
- `cost_governance_untagged_cost_usd` - Unattributed costs

Pie chart showing the split between tagged and untagged costs.

#### Cost Trend
**Queries:**
- `cost_governance_total_cost_usd` - Total cost over time
- `cost_governance_tagged_cost_usd` - Tagged cost trend
- `cost_governance_untagged_cost_usd` - Untagged cost trend

Line graph showing cost trends over the selected time period.

#### Cost by Namespace
**Query:** `sort_desc(cost_governance_namespace_cost_usd)`

Horizontal bar chart showing costs by namespace, sorted from most to least expensive.

### Compliance Overview Panels

#### Compliance Rate
**Query:** `cost_governance_compliance_rate`

Overall pod compliance percentage. Thresholds:
- Green: > 80% (excellent)
- Yellow: 50-80% (needs work)
- Red: < 50% (critical)

#### Pod Compliance Status
**Queries:**
- `cost_governance_compliant_pods`
- `cost_governance_violating_pods`

Donut chart showing the ratio of compliant to violating pods.

#### Violations by Type
**Query:** `cost_governance_violations_by_type`

Pie chart breaking down violations by type:
- MissingLabel - Required label is missing
- InvalidValue - Label value is invalid

#### Violations by Namespace
**Query:** `sort_desc(cost_governance_violations_by_namespace)`

Bar chart showing which namespaces have the most violations.

#### Violations by Label
**Query:** `sort_desc(cost_governance_violations_by_label)`

Bar chart showing which labels are most often missing or invalid.

### Performance Metrics Panels

#### Scan Duration
**Queries:**
- Average: `rate(cost_governance_scan_duration_seconds_sum[5m]) / rate(cost_governance_scan_duration_seconds_count[5m])`
- 95th Percentile: `histogram_quantile(0.95, rate(cost_governance_scan_duration_seconds_bucket[5m]))`

Shows how long compliance scans are taking.

#### Scan Errors Rate
**Query:** `rate(cost_governance_scan_errors_total[5m])`

Shows the rate of scan errors over time, broken down by error type.

---

## Customization

### Adjust Thresholds

**To change cost alert thresholds:**
1. Edit panel (click title → Edit)
2. Panel options → Thresholds
3. Adjust values and colors
4. Save dashboard

**Common customizations:**
- Total cost threshold (adjust based on your cluster size)
- Compliance rate threshold (adjust based on your org standards)
- Attribution rate threshold (adjust based on your goals)

### Add Alerts

You can add Grafana alerts to any panel:

1. Edit panel
2. Alert tab
3. Create alert rule
4. Set conditions (e.g., "cost > $100")
5. Configure notification channel

**Recommended alerts:**
- Cost exceeds budget
- Compliance drops below 80%
- Attribution rate below 50%
- Scan errors detected

### Modify Time Windows

Most queries use `[5m]` time windows for rate calculations. To adjust:

1. Edit panel
2. Modify query (e.g., change `[5m]` to `[15m]`)
3. Save

---

## Troubleshooting

### Dashboard shows "No Data"

**Check 1: Prometheus is scraping metrics**
```bash
# Port-forward to Prometheus
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090

# Open http://localhost:9090
# Query: cost_governance_total_cost_usd
# Should return data
```

**Check 2: ServiceMonitor is configured**
```bash
kubectl get servicemonitor -n monitoring cost-governance-operator
```

**Check 3: Metrics endpoint is accessible**
```bash
kubectl run test-curl --rm -it --image=curlimages/curl --restart=Never -- \
  curl http://cost-governance-operator.cost-governance-system.svc:8000/metrics
```

**Check 4: Cost collection has run**
```bash
# Cost data is collected hourly
kubectl logs -n cost-governance-system -l app=cost-governance-operator | grep "Cost collection complete"
```

### Panels show wrong datasource

If panels say "Datasource not found":

1. Dashboard Settings (gear icon)
2. JSON Model
3. Find/Replace `"uid": "prometheus"` with your Prometheus datasource UID
4. Save

**Find your Prometheus UID:**
```bash
kubectl get configmap -n monitoring prometheus-grafana -o yaml | grep prometheus
```

### Compliance panels empty but cost panels work

Compliance scans run every 5 minutes, cost collection every hour.

**Wait or trigger manually:**
```bash
kubectl annotate cg default-governance -n cost-governance-system \
  cost-governance.io/trigger-scan="$(date +%s)" --overwrite
```

---

## Dashboard Annotations

The dashboard uses Grafana's built-in annotation support. You can add annotations for:
- Cost collection events
- Compliance scan events
- Deployment changes
- Infrastructure changes

**To add annotations:**
1. Dashboard Settings → Annotations
2. New Query
3. Configure query to match events

---

## Exporting Dashboard

**To export for backup or sharing:**

1. Dashboard Settings (gear icon)
2. JSON Model
3. Copy JSON
4. Save to file

**Or via API:**
```bash
# Export dashboard JSON
curl -H "Authorization: Bearer $GRAFANA_API_KEY" \
  http://localhost:3000/api/dashboards/uid/cost-governance-operator | \
  jq .dashboard > backup.json
```

---

## Variables (Future Enhancement)

Currently, the dashboard is static. You can add template variables for:

**Cluster Selection:**
```promql
label_values(cost_governance_total_cost_usd, cluster)
```

**Namespace Filter:**
```promql
label_values(cost_governance_namespace_cost_usd, pod_namespace)
```

**To add variables:**
1. Dashboard Settings → Variables
2. Add variable
3. Update panel queries to use `$variable`

---

## Dashboard Links

Add useful links to the dashboard:

1. Dashboard Settings → Links
2. Add links to:
   - Prometheus UI
   - Operator documentation
   - Cost allocation reports
   - Compliance policies

---

## Refresh Behavior

- **Default refresh:** 30 seconds
- **Time range:** Last 24 hours
- **Auto-refresh:** Enabled

**To disable auto-refresh:**
- Click the refresh dropdown (top right)
- Select "Off"

---

## Screenshots

After importing, your dashboard will show:

**Cost Overview Section:**
- Gauge showing $10.87 total cost
- Attribution rate at 4.98%
- Pie chart with $0.54 tagged, $10.33 untagged
- Cost trend line graph
- Namespace bar chart with karpenter ($6.36) as top cost

**Compliance Overview Section:**
- Gauge showing 36.67% compliance
- Donut chart: 11 compliant, 19 violating
- Violations by type: 75 MissingLabel, 7 InvalidValue
- Namespace violations: monitoring (10), test-compliance (4), etc.

**Performance Section:**
- Scan duration ~0.45s average
- No errors (empty graph)
- 3 scans completed

---

## Next Steps

1. ✅ Import dashboard to Grafana
2. Set up alerts for cost thresholds
3. Create team-specific views (using variables)
4. Schedule reports (Grafana Enterprise)
5. Share dashboard URL with team

---

## Support

For issues or questions:
- Check operator logs: `kubectl logs -n cost-governance-system -l app=cost-governance-operator`
- Verify metrics: `curl http://localhost:8000/metrics`
- Review Prometheus targets: http://localhost:9090/targets
- See PROMETHEUS-METRICS.md for metric definitions
