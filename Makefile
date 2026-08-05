.PHONY: help install test test-unit test-cov lint security clean build info ecr-create-repo ecr-login push setup-pod-identity deploy-crds deploy-operator deploy-all undeploy logs deploy-registry deploy-governance deploy-test-apps deploy-test-violations deploy-tests undeploy-tests status violations reports events metrics grafana-connect prometheus-connect operator-connect restart dev-update dev-logs-violations dev-watch

# Configuration
# AWS_PROFILE must be provided: make <target> AWS_PROFILE=<profile>
ifndef AWS_PROFILE
$(error AWS_PROFILE is not set. Usage: make <target> AWS_PROFILE=<profile>)
endif

AWS_REGION ?= us-east-1

# Operator paths
OPERATOR_DIR := src/cost_governance_operator

# Docker/ECR configuration
AWS_ACCOUNT_ID := $(shell AWS_PROFILE=$(AWS_PROFILE) aws sts get-caller-identity --query Account --output text 2>/dev/null)
EKS_CLUSTER_NAME := $(shell kubectl config current-context 2>/dev/null | awk -F'/' '{print $$NF}')
ECR_REGISTRY := $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com
IMAGE_NAME := cost-governance-operator
IMAGE_TAG := latest
FULL_IMAGE := $(ECR_REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)

# IAM/Pod Identity configuration
IAM_ROLE_NAME := CostGovernanceOperatorRole
NAMESPACE := cost-governance-system
SERVICE_ACCOUNT := cost-governance-operator

help:
	@echo "Commands:"
	@echo ""
	@echo "=== Development ==="
	@echo "  make install           Install dependencies"
	@echo "  make test              Run all tests"
	@echo "  make test-unit         Run all unit tests"
	@echo "  make test-integ        Run all integration tests"
	@echo "  make test-cov          Run tests with coverage"
	@echo "  make test-cov-enforce  Run tests with coverage - fail if < 80%"
	@echo "  make lint              Run linters"
	@echo "  make security          Run security scanners"
	@echo "  make protoshield       Run ProtoShield scan"
	@echo "  make clean             Run cleanup"
	@echo ""
	@echo "=== Build & Deploy Operator ==="
	@echo "  make info              Display configuration"
	@echo "  make build             Build Docker image (linux/amd64)"
	@echo "  make ecr-create-repo   Create ECR repository if it doesn't exist"
	@echo "  make ecr-login         Authenticate Docker to ECR"
	@echo "  make push              Tag and push image to ECR"
	@echo "  make setup-pod-identity  Create IAM role and Pod Identity association"
	@echo "  make deploy-crds       Deploy CRDs (CostGovernance + ViolationReport)"
	@echo "  make deploy-operator   Deploy operator manifests"
	@echo "  make deploy-all        Full deployment (pod-identity + CRDs + operator)"
	@echo "  make undeploy          Remove operator from cluster"
	@echo "  make logs              Tail operator logs"
	@echo ""
	@echo "=== Deploy Test Resources ==="
	@echo "  make deploy-registry       Deploy registry ConfigMap"
	@echo "  make deploy-governance     Deploy CostGovernance instance"
	@echo "  make deploy-test-apps      Deploy compliant test applications"
	@echo "  make deploy-test-violations Deploy non-compliant test pods"
	@echo "  make deploy-tests          Deploy all test resources"
	@echo "  make undeploy-tests        Remove all test resources"
	@echo ""
	@echo "=== Monitor & Debug ==="
	@echo "  make status            Show operator and resource status"
	@echo "  make violations        Show recent violations"
	@echo "  make reports           List ViolationReports"
	@echo "  make events            Show compliance violation events"
	@echo "  make metrics           Port-forward to metrics endpoint"
	@echo "  make grafana-connect   Port-forward to Grafana dashboard"
	@echo "  make prometheus-connect  Port-forward to Prometheus UI"
	@echo "  make operator-connect  Port-forward to operator metrics"
	@echo "  make restart           Restart operator (triggers immediate scan)"
	@echo ""
	@echo "=== Development Helpers ==="
	@echo "  make dev-update        Push new image and restart operator"
	@echo "  make dev-logs-violations  Watch logs filtered for violations"
	@echo "  make dev-watch         Watch operator, CG, and VRs live"


###########################################################
# Install targets
###########################################################
install:
	uv sync

###########################################################
# Test targets
###########################################################

test:
	uv run pytest

test-cov:
	uv run pytest --cov=src/cost_governance_operator --cov-report=term-missing

test-cov-enforce:
	uv run pytest --cov=src/cost_governance_operator --cov-report=term-missing --cov-fail-under=80

test-unit:
	uv run pytest tests/unit

test-integ:
	uv run pytest tests/integ


###########################################################
# Linting targets
###########################################################
lint:
	uv run ruff check src/

###########################################################
# Security scanning targets
###########################################################
security:
	gitleaks detect . --verbose
	uv run bandit -r src/ -s B608


protoshield:
	AWS_REGION=$(AWS_REGION) AWS_PROFILE=$(AWS_PROFILE) protoshield scan --directory src/



###########################################################
# Operator targets
###########################################################

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

# Operator Build : Build operator docker image
build: info
	@echo "Building Docker image for linux/amd64..."
	docker build --platform linux/amd64 -t $(IMAGE_NAME):$(IMAGE_TAG) -f $(OPERATOR_DIR)/Dockerfile $(OPERATOR_DIR)
	@echo "✓ Image built: $(IMAGE_NAME):$(IMAGE_TAG)"

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

ecr-login:
	@echo "Logging into ECR..."
	AWS_PROFILE=$(AWS_PROFILE) aws ecr get-login-password --region $(AWS_REGION) | \
		docker login --username AWS --password-stdin $(ECR_REGISTRY)
	@echo "✓ Logged into ECR"

push: info ecr-create-repo ecr-login build
	@echo "Tagging image..."
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(FULL_IMAGE)
	@echo "Pushing to ECR..."
	docker push $(FULL_IMAGE)
	@echo "✓ Image pushed: $(FULL_IMAGE)"

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
		--assume-role-policy-document file://$(OPERATOR_DIR)/k8s_configs/iam/pod-identity-trust-policy.json \
		--description "IAM role for Cost Governance Operator" \
		2>/dev/null || echo "Role already exists, continuing..."
	@echo "2. Creating inline policy for Athena/S3 access"
	AWS_PROFILE=$(AWS_PROFILE) aws iam put-role-policy \
		--role-name $(IAM_ROLE_NAME) \
		--policy-name AthenaAccess \
		--policy-document file://$(OPERATOR_DIR)/k8s_configs/iam/athena-access-policy.json
	@echo "3. Creating Pod Identity association"
	AWS_PROFILE=$(AWS_PROFILE) aws eks create-pod-identity-association \
		--cluster-name $(EKS_CLUSTER_NAME) \
		--namespace $(NAMESPACE) \
		--service-account $(SERVICE_ACCOUNT) \
		--role-arn arn:aws:iam::$(AWS_ACCOUNT_ID):role/$(IAM_ROLE_NAME) \
		--region $(AWS_REGION) \
		2>/dev/null || echo "Association already exists, continuing..."
	@echo "✓ Pod Identity setup complete"

deploy-crds:
	@echo "Deploying CRDs..."
	kubectl apply -f $(OPERATOR_DIR)/k8s_configs/crds/
	@echo "✓ CRDs deployed"

deploy-operator: info
	@echo "Deploying operator..."
	kubectl apply -f $(OPERATOR_DIR)/k8s_configs/deployment/namespace.yaml
	kubectl apply -f $(OPERATOR_DIR)/k8s_configs/deployment/serviceaccount.yaml
	kubectl apply -f $(OPERATOR_DIR)/k8s_configs/deployment/role.yaml
	kubectl apply -f $(OPERATOR_DIR)/k8s_configs/deployment/rolebinding.yaml
	kubectl apply -f $(OPERATOR_DIR)/k8s_configs/deployment/service.yaml
	export AWS_ACCOUNT_ID=$(AWS_ACCOUNT_ID) AWS_REGION=$(AWS_REGION) && \
		envsubst < $(OPERATOR_DIR)/k8s_configs/deployment/deployment.yaml | kubectl apply -f -
	kubectl apply -f $(OPERATOR_DIR)/k8s_configs/monitoring/servicemonitor.yaml
	@echo "✓ Operator deployed"
	@echo ""
	@echo "Check status with:"
	@echo "  kubectl get pods -n $(NAMESPACE)"

deploy-all: setup-pod-identity deploy-crds deploy-operator
	@echo ""
	@echo "✓ Full deployment complete!"

undeploy:
	@echo "Removing operator..."
	kubectl delete -f $(OPERATOR_DIR)/k8s_configs/deployment/ --ignore-not-found=true
	kubectl delete -f $(OPERATOR_DIR)/k8s_configs/crds/ --ignore-not-found=true
	@echo "✓ Operator removed"
	@echo ""
	@echo "Note: IAM role and Pod Identity association not removed."
	@echo "To clean up manually:"
	@echo "  aws eks delete-pod-identity-association --cluster-name $(EKS_CLUSTER_NAME) --association-id <id>"
	@echo "  aws iam delete-role-policy --role-name $(IAM_ROLE_NAME) --policy-name AthenaAccess"
	@echo "  aws iam delete-role --role-name $(IAM_ROLE_NAME)"

logs:
	@echo "Tailing operator logs..."
	kubectl logs -n $(NAMESPACE) -l app=cost-governance-operator -f


###########################################################
# Test Resource Deployment targets
###########################################################

deploy-registry:
	@echo "Deploying registry ConfigMap..."
	kubectl apply -f $(OPERATOR_DIR)/k8s_configs/examples/cost-governance/registry-configmap.yaml
	@echo "✓ Registry deployed"

deploy-governance:
	@echo "Deploying CostGovernance instance..."
	kubectl apply -f $(OPERATOR_DIR)/k8s_configs/examples/cost-governance/cost-governance-instance.yaml
	@echo "✓ CostGovernance instance deployed"

deploy-test-apps:
	@echo "Deploying compliant test applications..."
	kubectl apply -f $(OPERATOR_DIR)/k8s_configs/examples/test-deployments/compliant-deployments.yaml
	@echo "✓ Test applications deployed"

deploy-test-violations:
	@echo "Deploying non-compliant test pods..."
	kubectl apply -f $(OPERATOR_DIR)/k8s_configs/examples/test-deployments/non-compliant-pods.yaml
	@echo "✓ Non-compliant test pods deployed"

deploy-tests: deploy-registry deploy-governance deploy-test-apps deploy-test-violations
	@echo ""
	@echo "✓ All test resources deployed!"
	@echo ""
	@echo "Wait 5 minutes for compliance scan, then:"
	@echo "  make logs"

undeploy-tests:
	@echo "Removing test resources..."
	kubectl delete -f $(OPERATOR_DIR)/k8s_configs/examples/test-deployments/ --ignore-not-found=true
	kubectl delete -f $(OPERATOR_DIR)/k8s_configs/examples/cost-governance/cost-governance-instance.yaml --ignore-not-found=true
	kubectl delete namespace test-apps test-compliance --ignore-not-found=true
	@echo "✓ Test resources removed"


###########################################################
# Monitor & Debug targets
###########################################################

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

violations:
	@echo "=========================================="
	@echo "Recent Compliance Violations"
	@echo "=========================================="
	@echo ""
	@kubectl logs -n $(NAMESPACE) -l app=cost-governance-operator --tail=100 | grep "Non-compliant pod:" || echo "No violations found in recent logs"

reports:
	@echo "=========================================="
	@echo "ViolationReports"
	@echo "=========================================="
	@echo ""
	@kubectl get vr -n $(NAMESPACE) --sort-by=.spec.scanTime 2>/dev/null || echo "No ViolationReports found"

events:
	@echo "=========================================="
	@echo "Compliance Violation Events"
	@echo "=========================================="
	@echo ""
	@kubectl get events --all-namespaces --field-selector reason=ComplianceViolation --sort-by='.lastTimestamp' | tail -20 || echo "No compliance violation events found"

metrics:
	@echo "Port-forwarding to metrics endpoint..."
	@echo "Metrics available at: http://localhost:8000/metrics"
	@echo "Press Ctrl+C to stop"
	@echo ""
	kubectl port-forward -n $(NAMESPACE) svc/cost-governance-operator 8000:8000

grafana-connect:
	@echo "Grafana admin password:"
	@kubectl get secret -n monitoring prometheus-grafana \
		-o jsonpath="{.data.admin-password}" | base64 --decode; echo
	@echo ""
	@echo "Port-forwarding to Grafana at http://localhost:3000 ..."
	@echo "Press Ctrl+C to stop"
	@echo ""
	kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80

prometheus-connect:
	@echo "Port-forwarding to Prometheus at http://localhost:9090 ..."
	@echo "Press Ctrl+C to stop"
	@echo ""
	kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090

operator-connect:
	@echo "Port-forwarding to operator metrics at http://localhost:8000/metrics ..."
	@echo "Press Ctrl+C to stop"
	@echo ""
	kubectl port-forward -n $(NAMESPACE) svc/cost-governance-operator 8000:8000

restart:
	@echo "Restarting operator (triggers immediate scan)..."
	kubectl rollout restart deployment/cost-governance-operator -n $(NAMESPACE)
	@echo "Waiting for rollout..."
	kubectl rollout status deployment/cost-governance-operator -n $(NAMESPACE)
	@echo "✓ Operator restarted"


###########################################################
# Development Helpers
###########################################################

dev-update: push restart
	@echo ""
	@echo "✓ Operator updated and restarted"
	@echo ""
	@echo "Watch logs with:"
	@echo "  make logs"

dev-logs-violations:
	@echo "Watching for violations in logs (Ctrl+C to stop)..."
	kubectl logs -n $(NAMESPACE) -l app=cost-governance-operator -f | grep --line-buffered "Non-compliant\|ViolationReport\|ComplianceScan"

dev-watch:
	@echo "Watching operator, CostGovernance, and ViolationReports..."
	@echo "Press Ctrl+C to stop"
	@echo ""
	watch -n 5 'kubectl get pods -n cost-governance-system && echo "" && kubectl get cg -n cost-governance-system && echo "" && kubectl get vr -n cost-governance-system --sort-by=.spec.scanTime | tail -5'


###########################################################
# Clean resource targets
###########################################################
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaning local Docker images..."
	docker rmi $(IMAGE_NAME):$(IMAGE_TAG) 2>/dev/null || true
	docker rmi $(FULL_IMAGE) 2>/dev/null || true
	@echo "✓ Clean complete"

	
