#!/usr/bin/env bash
# Compute and apply a JSON Patch that REMOVES the encryption + audit
# entries from the live machine config WITHOUT relying on hard-coded
# array indices.
#
# Why this exists: the previous runbook hard-coded patches like
# `/machine/files/3` and `/cluster/apiServer/extraVolumes/2`. If the
# live config has different ordering (e.g., a future PR adds an entry
# before our encryption block), the rollback amputates the WRONG
# entries — could delete nfsmount.conf or break apiserver networking.
#
# This script reads the live machineconfig, finds the indices of our
# specific paths/hostpaths by VALUE, builds a correct JSON Patch in
# REVERSE INDEX ORDER (so removals don't shift subsequent positions),
# and applies it.
#
# Usage:
#   /path/to/talos-encryption-rollback.sh dry-run
#   /path/to/talos-encryption-rollback.sh apply
#
# Audit-review findings addressed:
#   - correctness-reviewer finding #6: rollback patch indices are brittle.

set -euo pipefail

MODE=${1:-dry-run}
NODE=${TALOS_NODE:-192.168.10.89}
TALOSCONFIG=${TALOSCONFIG:-clusters/main/talos/generated/talosconfig}

if [ "$MODE" != "dry-run" ] && [ "$MODE" != "apply" ]; then
  echo "Usage: $0 [dry-run|apply]" >&2
  exit 2
fi

# Strings we want to remove (by value, not by index)
FILE_PATHS_TO_REMOVE=(
  "/var/etc/kubernetes/encryption-config.yaml"
  "/var/etc/kubernetes/audit-policy.yaml"
  "/var/log/k8s-audit/.keep"
)

VOLUME_HOSTPATHS_TO_REMOVE=(
  "/var/etc/kubernetes/encryption-config.yaml"
  "/var/etc/kubernetes/audit-policy.yaml"
  "/var/log/k8s-audit"
)

EXTRAARGS_KEYS_TO_REMOVE=(
  "encryption-provider-config"
  "audit-policy-file"
  "audit-log-path"
  "audit-log-maxsize"
  "audit-log-maxbackup"
)

# Fetch live machineconfig
echo "===Fetching live machineconfig from node $NODE==="
TMP=$(mktemp)
talosctl --talosconfig "$TALOSCONFIG" --nodes "$NODE" \
  get machineconfigs -o yaml > "$TMP"
SPEC=$(mktemp)
python3 -c "
import yaml,sys
docs = list(yaml.safe_load_all(open('$TMP')))
# get machineconfigs returns multiple resource docs; find the v1alpha1 one
for d in docs:
    if not isinstance(d, dict): continue
    if d.get('metadata',{}).get('id') == 'v1alpha1':
        spec = d.get('spec','')
        if isinstance(spec, str):
            spec = yaml.safe_load(spec)
        print(yaml.dump(spec))
        break
" > "$SPEC"

# Compute indices in reverse order (so removals don't shift)
echo "===Computing JSON Patch (reverse index order)==="
PATCH=$(python3 <<PYEOF
import yaml, json
spec = yaml.safe_load(open('$SPEC'))

patch = []

# machine.files
files = (spec.get('machine') or {}).get('files') or []
file_indices = []
for i, f in enumerate(files):
    if f.get('path') in [$(printf '"%s",' "${FILE_PATHS_TO_REMOVE[@]}")]:
        file_indices.append(i)
# Reverse so removals don't shift remaining indices
for i in sorted(file_indices, reverse=True):
    patch.append({"op": "remove", "path": f"/machine/files/{i}"})

# cluster.apiServer.extraVolumes
extra_vols = ((spec.get('cluster') or {}).get('apiServer') or {}).get('extraVolumes') or []
vol_indices = []
for i, v in enumerate(extra_vols):
    if v.get('hostPath') in [$(printf '"%s",' "${VOLUME_HOSTPATHS_TO_REMOVE[@]}")]:
        vol_indices.append(i)
for i in sorted(vol_indices, reverse=True):
    patch.append({"op": "remove", "path": f"/cluster/apiServer/extraVolumes/{i}"})

# cluster.apiServer.extraArgs (a map, not a list — index doesn't matter)
extra_args = ((spec.get('cluster') or {}).get('apiServer') or {}).get('extraArgs') or {}
for key in [$(printf '"%s",' "${EXTRAARGS_KEYS_TO_REMOVE[@]}")]:
    if key in extra_args:
        patch.append({"op": "remove", "path": f"/cluster/apiServer/extraArgs/{key}"})

print(json.dumps(patch, indent=2))
PYEOF
)

echo "$PATCH"
PATCH_FILE=$(mktemp --suffix=.json)
echo "$PATCH" > "$PATCH_FILE"

rm -f "$TMP" "$SPEC"

if [ "$MODE" = "dry-run" ]; then
  echo
  echo "===Dry-run of computed patch against live config==="
  talosctl --talosconfig "$TALOSCONFIG" --nodes "$NODE" \
    patch mc -p "@$PATCH_FILE" --mode=auto --dry-run
else
  echo
  echo "===APPLYING (mode=auto)==="
  echo "  This may reboot the node if any machine.files removals require it."
  read -rp "  Continue? (yes/N) " ANSWER
  if [ "$ANSWER" != "yes" ]; then
    echo "  Aborted."
    rm -f "$PATCH_FILE"
    exit 1
  fi
  talosctl --talosconfig "$TALOSCONFIG" --nodes "$NODE" \
    patch mc -p "@$PATCH_FILE" --mode=auto
fi

rm -f "$PATCH_FILE"
