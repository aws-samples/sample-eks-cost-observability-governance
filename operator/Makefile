# Cost Governance Operator - Makefile
# Build, push to ECR, and deploy to EKS

# Configuration
# AWS_PROFILE must be provided: make <target> AWS_PROFILE=<profile>
ifndef AWS_PROFILE
$(error AWS_PROFILE is not set. Usage: make <target> AWS_PROFILE=<profile>)
endif
AWS_REGION := us-east-1

# Get AWS Account ID dynamically from STS
AWS_ACCOUNT_ID := $(shell AWS_PROFILE=$(AWS_PROFILE) aws sts get-caller-identity --query Account --output text)

# Get EKS cluster name from current kubectl context (extracts part after last /)
EKS_CLUSTER_NAME := $(shell kubectl config current-context | awk -F'/' '{print $$NF}')

# Image configuration
ECR_REGISTRY := $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com
IMAGE_NAME := cost-governance-operator
IMAGE_TAG := latest
FULL_IMAGE := $(ECR_REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)

# IAM configuration
IAM_ROLE_NAME := CostGovernanceOperatorRole
NAMESPACE := cost-governance-system
SERVICE_ACCOUNT := cost-governance-operator

.PHONY: help
help:
	@echo "Cost Governance Operator - Available targets:"
	@echo ""
	@echo "=== Build & Deploy Operator ==="
	@echo "  info                  - Display configuration"
	@echo "  build                 - Build Docker image locally"
	@echo "  ecr-create-repo       - Create ECR repository if it doesn't exist"
	@echo "  ecr-login             - Authenticate Docker to ECR"
	@echo "  push                  - Tag and push image to ECR"
	@echo "  setup-pod-identity    - Create IAM role and Pod Identity association"
	@echo "  deploy-crds           - Deploy CRDs (CostGovernance + ViolationReport)"
	@echo "  deploy-operator       - Deploy operator manifests"
	@echo "  deploy-all            - Full deployment (pod-identity + CRDs + operator)"
	@echo "  undeploy              - Remove operator from cluster"
	@echo "  dev-update            - Push new image and restart operator (code changes)"
	@echo ""
	@echo "=== Deploy Test Resources ==="
	@echo "  deploy-registry       - Deploy registry ConfigMap"
	@echo "  deploy-governance     - Deploy CostGovernance instance"
	@echo "  deploy-test-apps      - Deploy compliant test applications"
	@echo "  deploy-test-violations - Deploy non-compliant test pods"
	@echo "  deploy-tests          - Deploy all test resources (registry + governance + pods)"
	@echo "  undeploy-tests        - Remove all test resources"
	@echo ""
	@echo "=== Monitor & Debug ==="
	@echo "  logs                  - Tail operator logs"
	@echo "  status                - Show operator and resource status"
	@echo "  violations            - Show recent violations"
	@echo "  reports               - List ViolationReports"
	@echo "  events                - Show compliance violation events"
	@echo "  metrics               - Port-forward to metrics endpoint"
	@echo "  grafana-connect       - Show Grafana password and port-forward to dashboard"
	@echo "  prometheus-connect    - Port-forward to Prometheus UI"
	@echo "  operator-connect      - Port-forward to operator metrics endpoint"
	@echo ""
	@echo "=== Cleanup ==="
	@echo "  clean                 - Clean local Docker images"
	@echo "  restart               - Restart operator (triggers immediate scan)"
	@echo ""

.PHONY: info
info:
	@echo "=========================================="
	@echo "Configuration:"
	@echo "=========================================="
	@echo "AWS Profile:      $(AWS_PROFILE)"
	@echo "AWS Region:       $(AWS_REGION)"
	@echo "AWS Account ID:   $(AWS_ACCOUNT_ID)"
	@echo "EKS Cluster:      $(EKS_CLUSTER_NAME)"
	@echo "Image Name:       $(IMAGE_NAME)"
	@echo "Full Image:       $(FULL_IMAGE)"
	@echo "IAM Role:         $(IAM_ROLE_NAME)"
	@echo "Namespace:        $(NAMESPACE)"
	@echo "=========================================="
	@echo ""

.PHONY: build
build: info
	@echo "Building Docker image for linux/amd64..."
	docker build --platform linux/amd64 -t $(IMAGE_NAME):$(IMAGE_TAG) .
	@echo "✓ Image built: $(IMAGE_NAME):$(IMAGE_TAG)"

.PHONY: ecr-create-repo
ecr-create-repo:
	@echo "Checking if ECR repository exists..."
	@AWS_PROFILE=$(AWS_PROFILE) aws ecr describe-repositories \
		--repository-names $(IMAGE_NAME) \
		--region $(AWS_REGION) \
		>/dev/null 2>&1 || \
	(echo "Creating ECR repository: $(IMAGE_NAME)" && \
	 AWS_PROFILE=$(AWS_PROFILE) aws ecr create-repository \
		--repository-name $(IMAGE_NAME) \
		--region $(AWS_REGION) \
		--image-scanning-configuration scanOnPush=true \
		--encryption-configuration encryptionType=AES256 && \
	 echo "✓ ECR repository created")
	@echo "✓ ECR repository exists: $(IMAGE_NAME)"

.PHONY: ecr-login
ecr-login:
	@echo "Logging into ECR..."
	AWS_PROFILE=$(AWS_PROFILE) aws ecr get-login-password --region $(AWS_REGION) | \
		docker login --username AWS --password-stdin $(ECR_REGISTRY)
	@echo "✓ Logged into ECR"

.PHONY: push
push: info ecr-create-repo ecr-login build
	@echo "Tagging image..."
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(FULL_IMAGE)
	@echo "Pushing to ECR..."
	docker push $(FULL_IMAGE)
	@echo "✓ Image pushed: $(FULL_IMAGE)"

.PHONY: setup-pod-identity
setup-pod-identity: info
	@echo "Setting up EKS Pod Identity..."
	@echo "0. Ensuring Pod Identity Agent addon is installed"
	AWS_PROFILE=$(AWS_PROFILE) aws eks create-addon \
		--cluster-name $(EKS_CLUSTER_NAME) \
		--addon-name eks-pod-identity-agent \
		--region $(AWS_REGION) \
		2>/dev/null || echo "Pod Identity Agent addon already installed, continuing..."

	@echo "1. Creating IAM role: $(IAM_ROLE_NAME)"
	AWS_PROFILE=$(AWS_PROFILE) aws iam create-role \
		--role-name $(IAM_ROLE_NAME) \
		--assume-role-policy-document file://k8s_configs/iam/pod-identity-trust-policy.json \
		--description "IAM role for Cost Governance Operator" \
		2>/dev/null || echo "Role already exists, continuing..."

	@echo "2. Creating inline policy for Athena/S3 access"
	AWS_PROFILE=$(AWS_PROFILE) aws iam put-role-policy \
		--role-name $(IAM_ROLE_NAME) \
		--policy-name AthenaAccess \
		--policy-document file://k8s_configs/iam/athena-access-policy.json

	@echo "3. Creating Pod Identity association"
	AWS_PROFILE=$(AWS_PROFILE) aws eks create-pod-identity-association \
		--cluster-name $(EKS_CLUSTER_NAME) \
		--namespace $(NAMESPACE) \
		--service-account $(SERVICE_ACCOUNT) \
		--role-arn arn:aws:iam::$(AWS_ACCOUNT_ID):role/$(IAM_ROLE_NAME) \
		--region $(AWS_REGION) \
		2>/dev/null || echo "Association already exists, continuing..."

	@echo "✓ Pod Identity setup complete"

.PHONY: deploy-crds
deploy-crds:
	@echo "Deploying CRDs..."
	kubectl apply -f k8s_configs/crds/
	@echo "✓ CRDs deployed"

.PHONY: deploy-operator
deploy-operator: info
	@echo "Deploying operator..."
	kubectl apply -f k8s_configs/deployment/namespace.yaml
	kubectl apply -f k8s_configs/deployment/serviceaccount.yaml
	kubectl apply -f k8s_configs/deployment/role.yaml
	kubectl apply -f k8s_configs/deployment/rolebinding.yaml
	kubectl apply -f k8s_configs/deployment/service.yaml
	export AWS_ACCOUNT_ID=$(AWS_ACCOUNT_ID) AWS_REGION=$(AWS_REGION) && \
		envsubst < k8s_configs/deployment/deployment.yaml | kubectl apply -f -
	kubectl apply -f k8s_configs/monitoring/servicemonitor.yaml
	@echo "✓ Operator deployed"
	@echo ""
	@echo "Check status with:"
	@echo "  kubectl get pods -n $(NAMESPACE)"
	@echo "  make logs"

.PHONY: deploy-all
deploy-all: setup-pod-identity deploy-crds deploy-operator
	@echo ""
	@echo "✓ Full deployment complete!"

.PHONY: undeploy
undeploy:
	@echo "Removing operator..."
	kubectl delete -f k8s_configs/deployment/ --ignore-not-found=true
	kubectl delete -f k8s_configs/crds/ --ignore-not-found=true
	@echo "✓ Operator removed"
	@echo ""
	@echo "Note: IAM role and Pod Identity association not removed."
	@echo "To clean up manually:"
	@echo "  aws eks delete-pod-identity-association --cluster-name $(EKS_CLUSTER_NAME) --association-id <id>"
	@echo "  aws iam delete-role-policy --role-name $(IAM_ROLE_NAME) --policy-name AthenaAccess"
	@echo "  aws iam delete-role --role-name $(IAM_ROLE_NAME)"

.PHONY: logs
logs:
	@echo "Tailing operator logs..."
	kubectl logs -n $(NAMESPACE) -l app=cost-governance-operator -f

.PHONY: clean
clean:
	@echo "Cleaning local Docker images..."
	docker rmi $(IMAGE_NAME):$(IMAGE_TAG) 2>/dev/null || true
	docker rmi $(FULL_IMAGE) 2>/dev/null || true
	@echo "✓ Clean complete"

# ==============================================================================
# Test Resource Deployment Targets
# ==============================================================================

.PHONY: deploy-registry
deploy-registry:
	@echo "Deploying registry ConfigMap..."
	kubectl apply -f k8s_configs/examples/cost-governance/registry-configmap.yaml
	@echo "✓ Registry deployed"
	@echo ""
	@echo "Verify with:"
	@echo "  kubectl get configmap cost-governance-registry -n $(NAMESPACE)"

.PHONY: deploy-governance
deploy-governance:
	@echo "Deploying CostGovernance instance..."
	kubectl apply -f k8s_configs/examples/cost-governance/cost-governance-instance.yaml
	@echo "✓ CostGovernance instance deployed"
	@echo ""
	@echo "Check status with:"
	@echo "  kubectl get cg -n $(NAMESPACE)"
	@echo "  kubectl get cg test-governance -n $(NAMESPACE) -o yaml"

.PHONY: deploy-test-apps
deploy-test-apps:
	@echo "Deploying compliant test applications..."
	kubectl apply -f k8s_configs/examples/test-deployments/compliant-deployments.yaml
	@echo "✓ Test applications deployed"
	@echo ""
	@echo "Check status with:"
	@echo "  kubectl get pods -n test-apps"
	@echo "  kubectl get deployments -n test-apps"

.PHONY: deploy-test-violations
deploy-test-violations:
	@echo "Deploying non-compliant test pods..."
	kubectl apply -f k8s_configs/examples/test-deployments/non-compliant-pods.yaml
	@echo "✓ Non-compliant test pods deployed"
	@echo ""
	@echo "Check status with:"
	@echo "  kubectl get pods -n test-compliance"
	@echo "Wait 5 minutes for compliance scan, then check violations with:"
	@echo "  make violations"

.PHONY: deploy-tests
deploy-tests: deploy-registry deploy-governance deploy-test-apps deploy-test-violations
	@echo ""
	@echo "=========================================="
	@echo "✓ All test resources deployed!"
	@echo "=========================================="
	@echo ""
	@echo "Wait 5 minutes for compliance scan, then:"
	@echo "  make status      - View overall status"
	@echo "  make violations  - View violations"
	@echo "  make reports     - View ViolationReports"
	@echo "  make events      - View K8s events"

.PHONY: undeploy-tests
undeploy-tests:
	@echo "Removing test resources..."
	kubectl delete -f k8s_configs/examples/test-deployments/ --ignore-not-found=true
	kubectl delete -f k8s_configs/examples/cost-governance/cost-governance-instance.yaml --ignore-not-found=true
	kubectl delete namespace test-apps test-compliance --ignore-not-found=true
	@echo "✓ Test resources removed"
	@echo ""
	@echo "Note: Registry ConfigMap kept (shared resource)"
	@echo "To remove registry:"
	@echo "  kubectl delete -f k8s_configs/examples/cost-governance/registry-configmap.yaml"

# ==============================================================================
# Monitoring & Debug Targets
# ==============================================================================

.PHONY: status
status:
	@echo "=========================================="
	@echo "Cost Governance Operator Status"
	@echo "=========================================="
	@echo ""
	@echo "=== Operator Pod ==="
	@kubectl get pods -n $(NAMESPACE) -l app=cost-governance-operator
	@echo ""
	@echo "=== CostGovernance Resources ==="
	@kubectl get cg -n $(NAMESPACE) 2>/dev/null || echo "No CostGovernance resources found"
	@echo ""
	@echo "=== ViolationReports (Last 5) ==="
	@kubectl get vr -n $(NAMESPACE) --sort-by=.spec.scanTime 2>/dev/null | tail -6 || echo "No ViolationReports found"
	@echo ""
	@echo "=== Test Pods ==="
	@echo "test-apps:"
	@kubectl get pods -n test-apps 2>/dev/null | grep -v "No resources" || echo "  No pods in test-apps"
	@echo "test-compliance:"
	@kubectl get pods -n test-compliance 2>/dev/null | grep -v "No resources" || echo "  No pods in test-compliance"

.PHONY: violations
violations:
	@echo "=========================================="
	@echo "Recent Compliance Violations"
	@echo "=========================================="
	@echo ""
	@if [ -x scripts/check_violations.sh ]; then \
		./scripts/check_violations.sh; \
	else \
		echo "Fetching violations from operator logs..."; \
		kubectl logs -n $(NAMESPACE) -l app=cost-governance-operator --tail=100 | grep "Non-compliant pod:" || echo "No violations found in recent logs"; \
	fi

.PHONY: reports
reports:
	@echo "=========================================="
	@echo "ViolationReports"
	@echo "=========================================="
	@echo ""
	@kubectl get vr -n $(NAMESPACE) --sort-by=.spec.scanTime 2>/dev/null || echo "No ViolationReports found"
	@echo ""
	@echo "View latest report details:"
	@echo "  kubectl get vr -n $(NAMESPACE) --sort-by=.spec.scanTime -o name | tail -1 | xargs kubectl get -n $(NAMESPACE) -o yaml"
	@echo ""
	@echo "Query violations in latest report:"
	@echo "  kubectl get vr -n $(NAMESPACE) --sort-by=.spec.scanTime -o name | tail -1 | xargs kubectl get -n $(NAMESPACE) -o json | jq '.spec.violations'"

.PHONY: events
events:
	@echo "=========================================="
	@echo "Compliance Violation Events"
	@echo "=========================================="
	@echo ""
	@kubectl get events --all-namespaces --field-selector reason=ComplianceViolation --sort-by='.lastTimestamp' | tail -20 || echo "No compliance violation events found"
	@echo ""
	@echo "Note: Events have 1-hour TTL by default"

.PHONY: metrics
metrics:
	@echo "Port-forwarding to metrics endpoint..."
	@echo "Metrics will be available at: http://localhost:8080/metrics"
	@echo ""
	@echo "In another terminal, run:"
	@echo "  curl http://localhost:8080/metrics | grep cost_governance"
	@echo ""
	@echo "Press Ctrl+C to stop port-forward"
	@echo ""
	kubectl port-forward -n $(NAMESPACE) deployment/cost-governance-operator 8080:8080

.PHONY: grafana-connect
grafana-connect:
	@echo "Grafana admin password:"
	@kubectl get secret -n monitoring prometheus-grafana \
		-o jsonpath="{.data.admin-password}" | base64 --decode; echo
	@echo ""
	@echo "Port-forwarding to Grafana at http://localhost:3000 ..."
	@echo "Press Ctrl+C to stop"
	@echo ""
	kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80

.PHONY: prometheus-connect
prometheus-connect:
	@echo "Port-forwarding to Prometheus at http://localhost:9090 ..."
	@echo "Press Ctrl+C to stop"
	@echo ""
	kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090

.PHONY: operator-connect
operator-connect:
	@echo "Port-forwarding to operator metrics at http://localhost:8000/metrics ..."
	@echo ""
	@echo "In another terminal, run:"
	@echo "  curl http://localhost:8000/metrics | grep cost_governance"
	@echo ""
	@echo "Press Ctrl+C to stop"
	@echo ""
	kubectl port-forward -n $(NAMESPACE) svc/cost-governance-operator 8000:8000

.PHONY: restart
restart:
	@echo "Restarting operator (triggers immediate scan)..."
	kubectl rollout restart deployment/cost-governance-operator -n $(NAMESPACE)
	@echo "Waiting for rollout..."
	kubectl rollout status deployment/cost-governance-operator -n $(NAMESPACE)
	@echo "✓ Operator restarted"
	@echo ""
	@echo "Watch logs with:"
	@echo "  make logs"

# ==============================================================================
# Quick Testing Targets
# ==============================================================================

.PHONY: test-quick
test-quick: status violations
	@echo ""
	@echo "=========================================="
	@echo "Quick Test Summary"
	@echo "=========================================="
	@echo ""
	@kubectl get cg -n $(NAMESPACE) -o json 2>/dev/null | jq '{compliance: {rate: .items[0].status.complianceRate, totalPods: .items[0].status.totalPods, violating: .items[0].status.violatingPods}}' || echo "No compliance data yet"

.PHONY: test-full
test-full:
	@echo "Running full test suite..."
	@echo "This will take ~6 minutes (wait for compliance scan)"
	@echo ""
	@echo "1. Deploying test resources..."
	@$(MAKE) deploy-tests
	@echo ""
	@echo "2. Waiting 5 minutes for compliance scan..."
	@sleep 300
	@echo ""
	@echo "3. Checking results..."
	@$(MAKE) test-quick
	@$(MAKE) reports
	@$(MAKE) events

# ==============================================================================
# Development Helpers
# ==============================================================================

.PHONY: dev-update
dev-update: push restart
	@echo ""
	@echo "✓ Operator updated and restarted"
	@echo ""
	@echo "Watch logs with:"
	@echo "  make logs"

.PHONY: dev-logs-violations
dev-logs-violations:
	@echo "Watching for violations in logs (Ctrl+C to stop)..."
	kubectl logs -n $(NAMESPACE) -l app=cost-governance-operator -f | grep --line-buffered "Non-compliant\|ViolationReport\|ComplianceScan"

.PHONY: dev-watch
dev-watch:
	@echo "Watching operator, CostGovernance, and ViolationReports..."
	@echo "Press Ctrl+C to stop"
	@echo ""
	watch -n 5 'kubectl get pods -n cost-governance-system && echo "" && kubectl get cg -n cost-governance-system && echo "" && kubectl get vr -n cost-governance-system --sort-by=.spec.scanTime | tail -5'
