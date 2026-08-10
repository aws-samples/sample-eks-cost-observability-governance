# Cost Governance Operator

A Kubernetes operator for EKS cost observability, attribution, and governance using AWS Split-Cost Allocation Data (CUR 2.0).

[![Kubernetes](https://img.shields.io/badge/kubernetes-1.28+-blue.svg)](https://kubernetes.io/)
[![AWS EKS](https://img.shields.io/badge/AWS-EKS-orange.svg)](https://aws.amazon.com/eks/)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

---

## Table of Contents

- [Introduction](#introduction)
- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Verification](#verification)
- [Further Reading](#further-reading)
- [Quick Start Cheat Sheet](#quick-start-cheat-sheet)

---

## Introduction

### What is the Cost Governance Operator?

AWS Split-Cost Allocation for EKS is a powerful feature — it breaks down shared node costs to individual pods in Cost and Usage Reports, giving you granular cost observability that wasn't possible before. Add cost-allocation tags, and you can further enrich your CUR reports to give you detailed insignts.  But visibility alone isn't enough. Without governance, that data is only as good as the labels on your workloads. If workloads are missing required tags, or if tags are used inconsistently your cost data will be fragmented and inaccurate. Your cost reports will fill up with "unallocated" line items and inconsistent data and stop being trustworthy.

The Cost Governance Operator bridges that gap. It's a Kubernetes operator that runs alongside your workloads on EKS and continuously validates that pods have the correct cost attribution labels, checks those values against an approved registry, and reports violations before they turn into orphaned costs. It also queries your CUR 2.0 data through Athena to surface actual dollar costs attributed to teams, namespaces, and applications — and separates application spend from cluster infrastructure overhead like Karpenter, CoreDNS, and monitoring.


### How It Works

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│   AWS Athena    │◄────────│  Cost Operator   │────────►│   Kubernetes    │
│   (CUR 2.0)     │  Query  │  (Kopf-based)    │  Scan   │   API Server    │
└─────────────────┘         └──────────────────┘         └─────────────────┘
                                     │
                                     ▼
                            ┌──────────────────┐
                            │   Prometheus     │
                            │   (15 metrics)   │
                            └──────────────────┘
                                     │
                                     ▼
                            ┌──────────────────┐
                            │     Grafana      │
                            │   (Dashboards)   │
                            └──────────────────┘
```

**Data Sources:**
- **AWS Cost and Usage Reports (CUR 2.0)** - Pod-level cost data with EKS split-cost allocation
- **Kubernetes API** - Live pod metadata, labels, and compliance state

**Outputs:**
- **CRD Status** - Cost and compliance data stored in `CostGovernance` resource status
- **ViolationReports** - Detailed, queryable compliance reports created after every scan
- **Kubernetes Events** - Per-pod `ComplianceViolation` warnings queryable via `kubectl get events --field-selector reason=ComplianceViolation`
- **Prometheus Metrics** - 15 metrics for cost, compliance, and performance
- **Grafana Dashboards** - Visual representation of cost trends and violations

### Key Benefits

- Real-time cost visibility directly in Kubernetes
- Attribute costs to teams with multiple dimensions (team, business unit, cost center, application, environment, etc.)
- Understand your platform costs vs application workload costs.
- Catch missing labels before they become orphaned costs
- Define governance policies as code in CRDs

---

## Features

### Cost Collection & Attribution
- ✅ **Hourly cost collection** from AWS Athena (CUR 2.0)
- ✅ **Namespace-level costs** - Understand which namespaces are most expensive
- ✅ **Cluster infrastructure breakdown** - Separate application costs from platform costs
- ✅ **Component-level detail** - See costs for CoreDNS, EBS CSI, Karpenter, Prometheus, etc.
- ✅ **Tagged vs untagged cost tracking** - Measure attribution coverage

### Compliance & Governance
- ✅ **Continuous pod scanning** (every 5 minutes)
- ✅ **Required label validation** - Ensure all pods have cost center, team, etc.
- ✅ **Allowed value validation** - Check labels against approved registries
- ✅ **ViolationReport CRDs** - Persistent, queryable compliance reports created after every scan
- ✅ **Kubernetes Events** - Per-pod `ComplianceViolation` warnings on non-compliant pods
- ✅ **Automatic report retention** - Old ViolationReports cleaned up, keeping the most recent 7
- ✅ **Violation tracking by namespace** - Identify which teams need help
- ✅ **Violation tracking by label** - Find the most commonly missing labels
- ✅ **Compliance rate calculation** - Overall percentage of compliant pods

### Observability
- ✅ **15 Prometheus metrics** exposed at `/metrics`
- ✅ **ServiceMonitor auto-discovery** for Prometheus Operator
- ✅ **Pre-built Grafana dashboard** with 17 panels
- ✅ **Performance metrics** - Scan duration and error rates
- ✅ **Operator version info** - Track deployed version

---

## Architecture

### Components

![Cost Governance Architecture](diagrams/cost-governance-architecture.drawio.png)

### AWS Integration

- **EKS Pod Identity**: Operator uses EKS Pod Identity to assume an IAM role
- **IAM Permissions**: Athena query execution, S3 read access to CUR bucket, Glue catalog access
- **CUR 2.0**: AWS Cost and Usage Reports with EKS split-cost allocation enabled
- **Athena Database**: (configurable via deployment.yaml

---

## Prerequisites

### 1. EKS Cluster with Split-Cost Allocation

Verify **split-cost allocation** is enabled in your Billing and Cost Management Console. to track pod-level costs. Additionally verify CUR report contains 'split_line_item_split_cost' column. (Note: data can take up to 24 hours to appear after enabling)


### 2. AWS Cost and Usage Reports (CUR 2.0)

You must have CUR 2.0 enabled with Athena integration.


### 4. Monitoring Stack (Prometheus + Grafana)

The operator exports metrics to Prometheus. You need Prometheus Operator with Grafana.

**Verify monitoring stack:**
```bash
# Check Prometheus
kubectl get prometheus -n monitoring

# Check Grafana
kubectl get deployment -n monitoring prometheus-grafana
```

**Install Prometheus + Grafana (using kube-prometheus-stack):**
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false
```

### 5. Tools

Ensure you have these tools installed:

```bash
# kubectl
kubectl version --client

# aws CLI
aws --version

# docker
docker --version

# make
make --version

# jq (for JSON parsing)
jq --version
```

---

## Installation

## Installation

### Step 1: Clone and Install Dependencies

```bash
git clone <repository-url>
cd sample-eks-cost-observability-governance

# Install Python dependencies (requires uv: https://docs.astral.sh/uv/)
make install AWS_PROFILE=your-profile
```

### Step 2: Configure for Your Environment

Update the deployment environment variables in `src/cost_governance_operator/k8s_configs/deployment/deployment.yaml`:

```yaml
env:
  - name: AWS_REGION
    value: "us-east-1"              # Your AWS region
  - name: ATHENA_DATABASE
    value: "billingdata"            # Your CUR Athena database name
  - name: ATHENA_TABLE
    value: "data"                   # Your CUR table name
  - name: ATHENA_S3_OUTPUT
    value: "s3://your-bucket/queryresults/"  # S3 path for Athena query results
  - name: EKS_CLUSTER_NAME
    value: "your-cluster-name"      # Auto-detected if not set, but explicit is safer
  - name: COST_LOOKBACK_DAYS
    value: "7"                      # Number of days of cost data to query
```

### Step 3: Update IAM Policy

Edit `src/cost_governance_operator/k8s_configs/iam/athena-access-policy.json` and update the S3 bucket ARNs to match your account:

```json
{
  "Sid": "S3AthenaResultsBucket",
  "Resource": [
    "arn:aws:s3:::your-bucket",
    "arn:aws:s3:::your-bucket/*"
  ]
},
{
  "Sid": "S3CURDataRead",
  "Resource": [
    "arn:aws:s3:::your-cur-bucket",
    "arn:aws:s3:::your-cur-bucket/*"
  ]
}
```

If your CUR data and Athena results share the same bucket (different prefixes), use the same bucket ARN for both statements.

### Step 4: Build and Push Image

```bash
make push AWS_PROFILE=your-profile
```

This will:
- Create the ECR repository if it doesn't exist
- Build the Docker image (linux/amd64)
- Authenticate to ECR
- Tag and push the image

### Step 5: Deploy the Operator

```bash
make deploy-all AWS_PROFILE=your-profile
```

This will:
- Install the EKS Pod Identity Agent addon (if not already present)
- Create IAM role (`CostGovernanceOperatorRole`) with Athena/S3 permissions
- Create EKS Pod Identity association
- Deploy CRDs (`CostGovernance`, `ViolationReport`)
- Deploy the operator, service, and ServiceMonitor to `cost-governance-system` namespace

### Step 6: Create a CostGovernance Instance

```bash
make deploy-governance AWS_PROFILE=your-profile
```

Or create manually:

```yaml
apiVersion: cost-governance.io/v1alpha1
kind: CostGovernance
metadata:
  name: default-governance
  namespace: cost-governance-system
spec:
  enforcementMode: audit
  requiredLabels:
    - cost-center
    - business-unit
    - team
    - application
    - environment
  registryConfigMap:
    name: cost-governance-registry
    namespace: cost-governance-system
```

### Step 7: Verify

```bash
# Check operator is running
kubectl get pods -n cost-governance-system

# Check cost and compliance data (cost data appears within ~1 min, compliance within 5 min)
kubectl get cg -n cost-governance-system -o wide
```

Expected output:
```
NAME                 TOTAL COST   APP COST   INFRA COST   COMPLIANCE   ATTRIBUTION   TOTAL PODS   AGE
default-governance   $18.13       $2.74      $10.28       36.67        7.7           252          5m
```

---

## Verification

### 1. Verify Operator is Running

```bash
# Check pod status
kubectl get pods -n cost-governance-system

# Expected output:
# NAME                                        READY   STATUS    RESTARTS   AGE
# cost-governance-operator-<hash>             1/1     Running   0          2m
```

### 2. Check Operator Logs

```bash
make logs

# Or manually:
kubectl logs -n cost-governance-system -l app=cost-governance-operator -f
```

**Look for:**
```
INFO: Prometheus metrics server started on port 8000 at /metrics
INFO: Kopf operator started
INFO: Handler 'create_fn' succeeded.
```

### 3. Verify CostGovernance Resource

```bash
kubectl get cg -n cost-governance-system
#expected output:
NAME                 TOTAL COST   APP COST   INFRA COST   AGE
default-governance   $51.66       $2.64      $19.10       6h28m

```

### 4. Check Cost Collection Status

```bash
kubectl get cg default-governance -n cost-governance-system -o jsonpath='{.status.costData}' | jq .
```

**Expected output:**
```json
{
  "totalCost": "10.87",
  "attributionRate": "13.80",
  "taggedCost": "1.50",
  "untaggedCost": "9.37",
  "lastCollectionTime": "2026-04-26T10:30:00Z",
  "clusterCostBreakdown": {
    "applicationCost": "1.50",
    "clusterInfrastructureCost": "9.37",
    "byComponent": [...]
  }
}
```

### 5. Verify Prometheus Metrics

**Port-forward to operator:**
```bash
kubectl port-forward -n cost-governance-system svc/cost-governance-operator 8000:8000
```

**Check metrics endpoint:**
```bash
curl http://localhost:8000/metrics | grep "^cost_governance"
```

**Expected output:**
```
cost_governance_total_cost_usd{cluster="your-cluster"} 10.87
cost_governance_attribution_rate{cluster="your-cluster"} 13.80
cost_governance_compliance_rate{governance_name="default-governance"} 36.67
...
```

### 6. Verify ServiceMonitor

```bash
kubectl get servicemonitor -n monitoring cost-governance-operator
```

**Expected output:**
```
NAME                        AGE
cost-governance-operator    5m
```

### 7. Check Prometheus is Scraping

**Port-forward to Prometheus:**
```bash
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090
```

**Open Prometheus UI:**
```
http://localhost:9090
```

**Query for metrics:**
```promql
cost_governance_total_cost_usd
```

**Expected:** Should return data points

### 8. Verify Grafana Dashboard (Optional)

**Port-forward to Grafana:**
```bash
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
```

**Get Grafana admin password:**
```bash
kubectl get secret -n monitoring prometheus-grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode; echo
```

**Open Grafana:**
```
http://localhost:3000
```

**Import dashboard:**
- See [Grafana Dashboard](./OPERATOR-DETAILED-GUIDE.md#grafana-dashboard) in the detailed guide

---

## Further Reading

For detailed documentation on metrics, cost attribution, violation reports, configuration, Grafana dashboards, troubleshooting, and advanced usage, see:

**[OPERATOR-DETAILED-GUIDE.md](./OPERATOR-DETAILED-GUIDE.md)**

---

## Quick Start Cheat Sheet

```bash
# 1. Build and deploy
make push AWS_PROFILE=<profile> && make deploy-all AWS_PROFILE=<profile>

# 2. Deploy governance policy and test resources
make deploy-tests AWS_PROFILE=<profile>

# 3. Check status
make status AWS_PROFILE=<profile>

# 4. View cost data
kubectl get cg default-governance -n cost-governance-system -o jsonpath='{.status.costData}' | jq .

# 5. Check metrics
make operator-connect AWS_PROFILE=<profile>
# In another terminal: curl http://localhost:8000/metrics | grep cost_governance

# 6. View violations
make violations AWS_PROFILE=<profile>

# 7. Tail logs
make logs AWS_PROFILE=<profile>
```

---

## License

MIT License - see [LICENSE](./LICENSE) file for details.

---

## Contributing

Contributions welcome! Please open an issue or pull request.

1. Fork repository
2. Create feature branch
3. Make changes
4. Run `make lint && make test`
5. Submit pull request

---

## Support

For issues, questions, or feature requests:
- Open an issue on GitHub
- Check [Troubleshooting](./OPERATOR-DETAILED-GUIDE.md#troubleshooting) in the detailed guide
- Review operator logs: `make logs`
