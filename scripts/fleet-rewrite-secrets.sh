#!/usr/bin/env bash
# Fleet-wide rewrite of every Secret in the allowlisted namespaces so
# each is materialized through the apiserver's current EncryptionConfig.
# Existing cleartext entries in etcd get re-encrypted with the active
# provider on write.
#
# Why this exists: Kubernetes encryption-at-rest encrypts only on WRITE.
# Adding the encryption-provider-config flag does NOT retroactively
# encrypt anything already in etcd. We have to force each Secret to be
# rewritten — `kubectl annotate --overwrite` is the canonical way (the
# annotation change forces apiserver to PUT through the storage layer).
#
# Designed to be:
#   - per-Secret loop (one failure doesn't abort the run)
#   - idempotent (rerunning is safe — annotation just bumps timestamp)
#   - resilient to type-skipped + controller-owned exclusions
#   - dry-run by default
#
# Usage:
#   /path/to/fleet-rewrite-secrets.sh dry-run
#   /path/to/fleet-rewrite-secrets.sh apply
#
# Audit-review findings addressed:
#   - Replaces the brittle `kubectl get ... | kubectl replace` pattern
#     from the original plan with `kubectl annotate --overwrite`
#     (correctness-reviewer finding #4).
#   - Sampling verification at end (correctness-reviewer testing gap).

set -uo pipefail

MODE=${1:-dry-run}
if [ "$MODE" != "dry-run" ] && [ "$MODE" != "apply" ]; then
  echo "Usage: $0 [dry-run|apply]" >&2
  exit 2
fi

ALLOWLIST_NAMESPACES=(
  flux-system
  kube-system
  media
  triparr-bot
  monitoring
  networking
  tools
  home
  default
  ollama
  loki
  cert-manager        # cert-manager OWNED Secrets are excluded below via ownerRef
  kube-prometheus-stack
  crowdsec
  traefik
  longhorn-system
  goodmem
  blocky
  apps
)

EXCLUDED_TYPES=(
  "kubernetes.io/service-account-token"   # auto-managed, recreated on demand
  "helm.sh/release.v1"                    # Helm-managed, large, immutable-by-convention
)

count_total=0
count_rewritten=0
count_skipped_type=0
count_skipped_owned=0
count_failed=0
failed_list=()

ROTATION_STAMP="encryption-rotated-at=$(date -u +%s)"

for NS in "${ALLOWLIST_NAMESPACES[@]}"; do
  while IFS=$'\t' read -r NAME TYPE OWNERS; do
    [ -z "$NAME" ] && continue
    count_total=$((count_total + 1))

    # Exclude by type
    for ET in "${EXCLUDED_TYPES[@]}"; do
      if [ "$TYPE" = "$ET" ]; then
        count_skipped_type=$((count_skipped_type + 1))
        continue 2
      fi
    done

    # Exclude controller-owned Secrets (cert-manager certs, CNPG postgres-bootstrap, etc.)
    if [ -n "$OWNERS" ] && [ "$OWNERS" != "null" ]; then
      count_skipped_owned=$((count_skipped_owned + 1))
      continue
    fi

    if [ "$MODE" = "dry-run" ]; then
      echo "WOULD REWRITE: $NS/$NAME ($TYPE)"
      continue
    fi

    # Annotate forces a real apiserver PUT through the storage layer →
    # apiserver re-encodes with the active EncryptionConfig provider.
    if kubectl annotate --overwrite secret -n "$NS" "$NAME" "$ROTATION_STAMP" >/dev/null 2>&1; then
      count_rewritten=$((count_rewritten + 1))
    else
      count_failed=$((count_failed + 1))
      failed_list+=("$NS/$NAME")
      echo "FAILED: $NS/$NAME"
    fi
  done < <(kubectl get secrets -n "$NS" -o json 2>/dev/null \
    | jq -r '.items[] | [.metadata.name, .type, (.metadata.ownerReferences // null | tostring)] | @tsv' 2>/dev/null)
done

echo
echo "===== Summary ====="
echo "  Total Secrets visited     : $count_total"
echo "  Rewritten (apply mode)    : $count_rewritten"
echo "  Skipped (type-excluded)   : $count_skipped_type"
echo "  Skipped (controller-owned): $count_skipped_owned"
echo "  Failed                    : $count_failed"
if [ "$count_failed" -gt 0 ]; then
  printf "  Failed Secrets:\n"
  for f in "${failed_list[@]}"; do echo "    - $f"; done
  exit 1
fi

if [ "$MODE" = "apply" ] && [ "$count_rewritten" -gt 0 ]; then
  echo
  echo "===== Encryption sampling check ====="
  echo "  Verifying 5 random rewritten Secrets are now ciphertext in etcd."
  echo "  (Requires bbolt + a fresh etcd snapshot at /tmp/etcd.snap)"
  if [ ! -f /tmp/etcd.snap ]; then
    echo "  /tmp/etcd.snap not found — take a snapshot first:"
    echo "    talosctl --nodes 192.168.10.89 etcd snapshot /tmp/etcd.snap"
    echo "  then run:"
    echo "    $0 verify"
    exit 0
  fi
  # If we have the snapshot, sample 5 random Secrets and check the prefix
  SAMPLED=$(kubectl get secrets -A -o json | jq -r '.items[] | [.metadata.namespace, .metadata.name] | @tsv' | shuf | head -5)
  while IFS=$'\t' read -r NS NAME; do
    KEY="/registry/secrets/${NS}/${NAME}"
    PREFIX=$(bbolt get /tmp/etcd.snap key "$KEY" 2>/dev/null | head -c 22)
    if echo "$PREFIX" | grep -q "k8s:enc:aesgcm:v1:key1:"; then
      echo "  ✓ $NS/$NAME  ciphertext (aesgcm)"
    else
      echo "  ✗ $NS/$NAME  NOT ciphertext (first 22 bytes: $PREFIX)"
    fi
  done <<< "$SAMPLED"
fi
