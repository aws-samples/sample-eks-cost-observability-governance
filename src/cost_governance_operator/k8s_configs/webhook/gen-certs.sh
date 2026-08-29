#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Generate a self-signed CA + serving certificate for the admission webhook and
# create/update the Kubernetes Secret the operator mounts, plus print the
# base64 CA bundle to inject into the ValidatingWebhookConfiguration.
#
# The cert is issued for the operator Service DNS names so the EKS API server can
# verify the TLS connection when it calls the webhook.
#
# Usage:
#   ./gen-certs.sh                 # apply the Secret and patch the webhook config
#   ./gen-certs.sh --print-only    # just generate + print the caBundle, no apply
set -euo pipefail

NAMESPACE="cost-governance-system"
SERVICE="cost-governance-operator"
SECRET_NAME="cost-governance-webhook-cert"
WEBHOOK_CONFIG="cost-governance.io"
CN="${SERVICE}.${NAMESPACE}.svc"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT

echo "==> Generating self-signed CA..."
openssl genrsa -out "${WORKDIR}/ca.key" 2048 >/dev/null 2>&1
openssl req -x509 -new -nodes -key "${WORKDIR}/ca.key" -sha256 -days 3650 \
  -subj "/CN=cost-governance-webhook-ca" \
  -out "${WORKDIR}/ca.crt" >/dev/null 2>&1

echo "==> Generating serving key + CSR for ${CN}..."
openssl genrsa -out "${WORKDIR}/tls.key" 2048 >/dev/null 2>&1

cat > "${WORKDIR}/csr.conf" <<EOF
[req]
req_extensions = v3_req
distinguished_name = dn
[dn]
[v3_req]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names
[alt_names]
DNS.1 = ${SERVICE}.${NAMESPACE}.svc
DNS.2 = ${SERVICE}.${NAMESPACE}.svc.cluster.local
DNS.3 = ${SERVICE}.${NAMESPACE}
DNS.4 = ${SERVICE}
EOF

openssl req -new -key "${WORKDIR}/tls.key" -subj "/CN=${CN}" \
  -config "${WORKDIR}/csr.conf" -out "${WORKDIR}/tls.csr" >/dev/null 2>&1

echo "==> Signing serving cert with the CA..."
openssl x509 -req -in "${WORKDIR}/tls.csr" \
  -CA "${WORKDIR}/ca.crt" -CAkey "${WORKDIR}/ca.key" -CAcreateserial \
  -out "${WORKDIR}/tls.crt" -days 3650 -sha256 \
  -extensions v3_req -extfile "${WORKDIR}/csr.conf" >/dev/null 2>&1

CA_BUNDLE="$(base64 < "${WORKDIR}/ca.crt" | tr -d '\n')"

if [[ "${1:-}" == "--print-only" ]]; then
  echo "==> caBundle (base64):"
  echo "${CA_BUNDLE}"
  exit 0
fi

echo "==> Creating/updating Secret ${NAMESPACE}/${SECRET_NAME}..."
kubectl create secret generic "${SECRET_NAME}" \
  --namespace "${NAMESPACE}" \
  --from-file=tls.crt="${WORKDIR}/tls.crt" \
  --from-file=tls.key="${WORKDIR}/tls.key" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> Rendering and applying ValidatingWebhookConfiguration ${WEBHOOK_CONFIG} with the CA bundle..."
# Substitute the real CA bundle into the manifest's ${CA_BUNDLE} token, then
# apply. We render+apply here (rather than applying a placeholder and patching)
# so kubectl never sees an invalid base64 caBundle value.
CONFIG_FILE="$(dirname "$0")/validating-webhook-configuration.yaml"
CA_BUNDLE="${CA_BUNDLE}" envsubst '${CA_BUNDLE}' < "${CONFIG_FILE}" | kubectl apply -f -

echo "==> Done. Secret and webhook config with caBundle are in place."
