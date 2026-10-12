#!/usr/bin/env bash
# Fail when the pinned Kubernetes minor is newer than the pinned Talos release
# can run.
#
# Talos ships a hard ceiling on the Kubernetes minor it supports: the
# DefaultKubernetesVersion constant in pkg/machinery/constants/constants.go at
# the Talos tag. A Renovate bump of ghcr.io/siderolabs/kubelet past that ceiling
# makes the `kubernetes` system-upgrade plan run `talosctl upgrade-k8s` to a
# version the node's Talos cannot run, so this check must fail the PR before it
# merges.
#
# Checks, in order:
#   1. upgradesettings.yaml and talconfig.yaml agree on both versions.
#   2. Fetch constants.go for the pinned Talos tag from siderolabs/talos. Any
#      fetch or parse failure is a hard failure; this never fails open.
#   3. KUBERNETES_VERSION minor <= DefaultKubernetesVersion minor.
#
# Usage: .github/scripts/check-talos-k8s-compat.sh [repo-root]
#   repo-root defaults to the repository containing this script.
# Exit 0 on pass, 1 on any failure. Runbook: docs/runbooks/talos-kubernetes-upgrade-order.md
set -euo pipefail

REPO_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
UPGRADE_SETTINGS="clusters/main/kubernetes/flux-system/flux/upgradesettings.yaml"
TALCONFIG="clusters/main/talos/talconfig.yaml"
CONSTANTS_BASE="https://raw.githubusercontent.com/siderolabs/talos"
CONSTANTS_PATH="pkg/machinery/constants/constants.go"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  if [ -n "${GITHUB_ACTIONS:-}" ]; then
    printf '::error::%s\n' "$*"
  fi
  exit 1
}

# read_key FILE KEY -> prints the scalar value of the first top-level-or-nested
# "KEY: value" line, with surrounding quotes and trailing comments stripped.
read_key() {
  local file="$1" key="$2" value
  value="$(grep -E "^[[:space:]]*${key}:[[:space:]]*[^[:space:]]" "$file" | head -n 1 \
    | sed -E "s/^[[:space:]]*${key}:[[:space:]]*//; s/[[:space:]]+#.*$//; s/^[\"']//; s/[\"']$//; s/[[:space:]]+$//")"
  [ -n "$value" ] || fail "could not read '${key}' from ${file}"
  printf '%s' "$value"
}

# strip_v v1.2.3 -> 1.2.3 ; fails on anything that is not MAJOR.MINOR.PATCH
strip_v() {
  local v="${1#v}"
  [[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]] || fail "'$1' is not a MAJOR.MINOR.PATCH version"
  printf '%s' "$v"
}

minor_of() { local v="$1"; v="${v#*.}"; printf '%s' "${v%%.*}"; }
major_of() { printf '%s' "${1%%.*}"; }

# fetch_constants REF OUTFILE -> 0 and writes the file, else prints why and
# returns 1. Caller decides whether that is fatal.
fetch_constants() {
  local ref="$1" out="$2" url code
  url="${CONSTANTS_BASE}/${ref}/${CONSTANTS_PATH}"
  if ! code="$(curl -sS --retry 3 --retry-delay 2 -o "$out" -w '%{http_code}' "$url" 2>"${out}.err")"; then
    printf 'network error fetching %s: %s' "$url" "$(tr -d '\n' <"${out}.err")"
    return 1
  fi
  if [ "$code" != "200" ]; then
    printf 'HTTP %s fetching %s' "$code" "$url"
    return 1
  fi
}

# default_k8s_version FILE -> prints X.Y.Z from DefaultKubernetesVersion
default_k8s_version() {
  grep -E '^[[:space:]]*DefaultKubernetesVersion[[:space:]]*=[[:space:]]*"[0-9]+\.[0-9]+\.[0-9]+"' "$1" \
    | head -n 1 | sed -E 's/.*"([0-9]+\.[0-9]+\.[0-9]+)".*/\1/'
}

for f in "$UPGRADE_SETTINGS" "$TALCONFIG"; do
  [ -f "$REPO_ROOT/$f" ] || fail "missing $f under repo root $REPO_ROOT"
done

# 1. The two pin files must agree.
US_TALOS="$(read_key "$REPO_ROOT/$UPGRADE_SETTINGS" TALOS_VERSION)"
US_K8S="$(read_key "$REPO_ROOT/$UPGRADE_SETTINGS" KUBERNETES_VERSION)"
TC_TALOS="$(read_key "$REPO_ROOT/$TALCONFIG" talosVersion)"
TC_K8S="$(read_key "$REPO_ROOT/$TALCONFIG" kubernetesVersion)"

TALOS="$(strip_v "$US_TALOS")"
K8S="$(strip_v "$US_K8S")"
[ "$TALOS" = "$(strip_v "$TC_TALOS")" ] \
  || fail "Talos version disagrees: ${UPGRADE_SETTINGS} TALOS_VERSION=${US_TALOS} vs ${TALCONFIG} talosVersion=${TC_TALOS}"
[ "$K8S" = "$(strip_v "$TC_K8S")" ] \
  || fail "Kubernetes version disagrees: ${UPGRADE_SETTINGS} KUBERNETES_VERSION=${US_K8S} vs ${TALCONFIG} kubernetesVersion=${TC_K8S}"

echo "Pinned: Talos v${TALOS}, Kubernetes v${K8S} (both files agree)"

# 2. Supported ceiling from the Talos tag. Fetch/parse failure is fatal.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if ! why="$(fetch_constants "v${TALOS}" "$TMP/constants.go")"; then
  fail "could not determine supported Kubernetes version for Talos v${TALOS}: ${why}. Refusing to pass without evidence (does tag v${TALOS} exist in siderolabs/talos?)."
fi
SUPPORTED="$(default_k8s_version "$TMP/constants.go")"
[ -n "$SUPPORTED" ] \
  || fail "fetched constants.go for Talos v${TALOS} but found no DefaultKubernetesVersion = \"X.Y.Z\" line; the upstream layout changed, fix this script"

echo "Talos v${TALOS} DefaultKubernetesVersion = ${SUPPORTED} (supports Kubernetes minor <= $(major_of "$SUPPORTED").$(minor_of "$SUPPORTED"))"

# 3. Compare majors, then minors.
K8S_MAJOR="$(major_of "$K8S")"; K8S_MINOR="$(minor_of "$K8S")"
SUP_MAJOR="$(major_of "$SUPPORTED")"; SUP_MINOR="$(minor_of "$SUPPORTED")"
TALOS_MINOR="$(minor_of "$TALOS")"

if [ "$K8S_MAJOR" -gt "$SUP_MAJOR" ] || { [ "$K8S_MAJOR" -eq "$SUP_MAJOR" ] && [ "$K8S_MINOR" -gt "$SUP_MINOR" ]; }; then
  # Each Talos minor raises the supported Kubernetes minor by one, so the Talos
  # minor needed is offset by the same gap. Confirm against that release
  # branch when reachable; otherwise say it is expected rather than confirmed.
  NEEDED_MINOR=$(( TALOS_MINOR + K8S_MINOR - SUP_MINOR ))
  NEEDED="$(major_of "$TALOS").${NEEDED_MINOR}"
  CONFIRM="(expected; could not confirm from the release-${NEEDED} branch)"
  if fetch_constants "release-${NEEDED}" "$TMP/needed.go" >/dev/null 2>&1; then
    NEEDED_DEFAULT="$(default_k8s_version "$TMP/needed.go")"
    if [ -n "$NEEDED_DEFAULT" ] && [ "$(minor_of "$NEEDED_DEFAULT")" -ge "$K8S_MINOR" ]; then
      CONFIRM="(release-${NEEDED} branch defaults to Kubernetes ${NEEDED_DEFAULT})"
    fi
  fi
  fail "Kubernetes v${K8S} is newer than Talos v${TALOS} can run: Talos v${TALOS} supports Kubernetes up to ${SUP_MAJOR}.${SUP_MINOR}.x. Bump TALOS_VERSION/talosVersion to a Talos ${NEEDED}.x release first ${CONFIRM}, or hold KUBERNETES_VERSION/kubernetesVersion at ${SUP_MAJOR}.${SUP_MINOR}.x. See docs/runbooks/talos-kubernetes-upgrade-order.md"
fi

echo "OK: Kubernetes v${K8S} is within the range Talos v${TALOS} supports"
