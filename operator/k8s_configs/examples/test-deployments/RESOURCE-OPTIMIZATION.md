# Test Deployment Resource Optimization

**Date:** 2026-04-25  
**Reason:** Reduced resource requests to fit on smaller Karpenter NodePool instances

---

## Changes Made

### compliant-deployments.yaml

| Deployment | Old CPU | New CPU | Old Memory | New Memory | Change |
|------------|---------|---------|------------|------------|--------|
| **ml-training** | **2000m** | **100m** | **4Gi** | **256Mi** | **95% reduction** |
| data-processor | 500m | 100m | 512Mi | 256Mi | 80% reduction |
| api-service | 250m | 50m | 256Mi | 128Mi | 80% reduction |
| sales-dashboard | 200m | 50m | 256Mi | 128Mi | 75% reduction |
| product-api | 100m | 100m | 128Mi | 128Mi | No change |

**Total Savings:**
- **CPU:** 3050m → 400m (87% reduction)
- **Memory:** 5376Mi → 1024Mi (81% reduction)

### non-compliant-pods.yaml

| Pod | Old CPU | New CPU | Old Memory | New Memory |
|-----|---------|---------|------------|------------|
| All test pods | 100m | 50m | 128Mi | 128Mi |
| compliant-pod-2 | 200m | 50m | 256Mi | 128Mi |

---

## Why This Was Needed

**Problem:**
- ml-training pod requested 2 CPU cores and 4GB memory
- Karpenter NodePool only allows instance types: t/m family, small/medium/large sizes
- t3.medium max: ~2 CPU cores (not enough for 2+ CPU after system overhead)
- m5.medium max: ~2 CPU cores (same issue)
- Result: "no instance type has enough resources"

**Solution:**
- These are **test/demo pods**, not production workloads
- Reduced all pods to minimal resources for testing purposes
- ml-training: 2 CPU → 100m (20x reduction!)
- Total cluster test overhead reduced by ~87%

---

## Impact

### Before
- **Total test pod requests:** ~3.1 CPU cores, ~5.5GB memory
- **Required:** At minimum m5.large or larger instances
- **Karpenter:** Could not provision (size limits)
- **Result:** Pods stuck in Pending

### After
- **Total test pod requests:** ~0.4 CPU cores, ~1GB memory
- **Required:** Can fit on t3.small (2 CPU, 2GB)
- **Karpenter:** Successfully provisions nodes
- **Result:** Pods schedule immediately

---

## Deployment Instructions

```bash
cd /Users/bdastur/code/incubator_apr25/incubator/eks_cost_observability_blog/operator

# Delete existing test deployments (if any)
kubectl delete -f k8s_configs/examples/test-deployments/ --ignore-not-found

# Wait for pods to terminate
kubectl wait --for=delete pods --all -n test-apps --timeout=60s
kubectl wait --for=delete pods --all -n test-compliance --timeout=60s

# Apply updated test deployments with lower resources
kubectl apply -f k8s_configs/examples/test-deployments/

# Verify pods schedule successfully
kubectl get pods -n test-apps
kubectl get pods -n test-compliance

# Check resource usage
kubectl top pods -n test-apps
kubectl top pods -n test-compliance
```

---

## Verification

```bash
# Check deployments have lower resource requests
kubectl get deployments -n test-apps -o custom-columns=\
NAME:.metadata.name,\
CPU:.spec.template.spec.containers[0].resources.requests.cpu,\
MEMORY:.spec.template.spec.containers[0].resources.requests.memory

# Expected output:
# NAME              CPU    MEMORY
# api-service       50m    128Mi
# data-processor    100m   256Mi
# ml-training       100m   256Mi
# product-api       100m   128Mi
# sales-dashboard   50m    128Mi
```

---

## Production Considerations

**Note:** These are **TEST** resources optimized for demo purposes.

**For production workloads:**
1. **ml-training:** Would need actual ML training resources (GPUs, high CPU/memory)
2. **data-processor:** Would need resources based on actual data volume
3. **api-service:** Would need resources based on traffic patterns
4. **Right-sizing:** Use Prometheus metrics to determine actual needs

**These test values are appropriate for:**
- ✅ Testing compliance validation
- ✅ Testing cost attribution
- ✅ Demo purposes
- ✅ CI/CD testing
- ❌ **NOT for production workloads**

---

## Karpenter NodePool Compatibility

These resources now fit comfortably on:

**Minimum instance:**
- t3.small: 2 CPU, 2GB memory (~$15/month)
- All test pods combined: 0.4 CPU, 1GB memory
- **Remaining capacity:** 80% available

**Recommended for test environment:**
- t3.medium: 2 CPU, 4GB memory (~$30/month)
- Plenty of room for test pods + operator + system overhead

---

## Rollback (If Needed)

If you need to restore higher resource requests:

```bash
# Edit deployments individually
kubectl edit deployment ml-training -n test-apps

# Change back to:
resources:
  requests:
    cpu: "2"
    memory: "4Gi"
  limits:
    cpu: "4"
    memory: "8Gi"
```

Or restore from git history.

---

## Files Modified

1. `k8s_configs/examples/test-deployments/compliant-deployments.yaml`
   - 5 deployments updated
   - All resource requests reduced

2. `k8s_configs/examples/test-deployments/non-compliant-pods.yaml`
   - 7 pods updated
   - All resource requests reduced to 50m CPU

---

## Related Issues

**Karpenter Error (Before Fix):**
```
could not schedule pod: no instance type has enough resources, 
requirements=... resources={"cpu":"2310m","memory":"4668Mi"}
```

**Resolution:** Reduced resources to fit within NodePool constraints.

---

**Optimization Complete!** ✅

Test pods now use minimal resources appropriate for testing/demo purposes.
