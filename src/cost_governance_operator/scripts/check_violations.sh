#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Check Individual Pod Violations
#
# This script extracts and displays individual pod compliance violations
# from the Cost Governance Operator logs.
#

set -e

NAMESPACE="cost-governance-system"
APP_LABEL="app=cost-governance-operator"

echo "=============================================="
echo "  Cost Governance - Violation Report"
echo "=============================================="
echo ""

# Check if operator is running
if ! kubectl get pods -n "$NAMESPACE" -l "$APP_LABEL" &>/dev/null; then
    echo "❌ Error: Operator not found in namespace $NAMESPACE"
    exit 1
fi

POD_NAME=$(kubectl get pods -n "$NAMESPACE" -l "$APP_LABEL" -o jsonpath='{.items[0].metadata.name}')

if [ -z "$POD_NAME" ]; then
    echo "❌ Error: No operator pod found"
    exit 1
fi

echo "📋 Operator Pod: $POD_NAME"
echo ""

# Get recent logs
echo "Fetching recent violations..."
echo ""

# Extract non-compliant pod entries
VIOLATIONS=$(kubectl logs -n "$NAMESPACE" "$POD_NAME" --tail=1000 | grep "Non-compliant pod:" || true)

if [ -z "$VIOLATIONS" ]; then
    echo "✅ No violations found in recent logs!"
    echo ""
    echo "This could mean:"
    echo "  1. All pods are compliant"
    echo "  2. No compliance scan has run yet (wait 5 minutes)"
    echo "  3. Logs have rotated (restart operator to see fresh scan)"
    exit 0
fi

# Count violations
VIOLATION_COUNT=$(echo "$VIOLATIONS" | wc -l | tr -d ' ')
echo "❌ Found $VIOLATION_COUNT violations:"
echo ""

# Group by violation type
echo "=== Violations by Type ==="
echo ""

echo "🔸 Missing Labels:"
echo "$VIOLATIONS" | grep "Missing required label" | sed 's/.*Non-compliant pod: /  - /' || echo "  None"
echo ""

echo "🔸 Invalid Cost Centers:"
echo "$VIOLATIONS" | grep "Invalid cost-center" | sed 's/.*Non-compliant pod: /  - /' || echo "  None"
echo ""

echo "🔸 Invalid Teams:"
echo "$VIOLATIONS" | grep "Invalid team" | sed 's/.*Non-compliant pod: /  - /' || echo "  None"
echo ""

echo "🔸 Invalid Environments:"
echo "$VIOLATIONS" | grep "Invalid environment" | sed 's/.*Non-compliant pod: /  - /' || echo "  None"
echo ""

echo "🔸 Invalid Business Units:"
echo "$VIOLATIONS" | grep "Invalid business-unit" | sed 's/.*Non-compliant pod: /  - /' || echo "  None"
echo ""

# Show full details
echo ""
echo "=== Full Violation Details ==="
echo ""
echo "$VIOLATIONS" | sed 's/.*Non-compliant pod: //' | sort

echo ""
echo "=============================================="
echo "  Report Complete"
echo "=============================================="
echo ""
echo "💡 Tips:"
echo "  - To fix violations, add/correct labels on pods"
echo "  - Check registry: kubectl get cm cost-governance-registry -n cost-governance-system -o yaml"
echo "  - Force rescan: kubectl rollout restart deployment/cost-governance-operator -n cost-governance-system"
