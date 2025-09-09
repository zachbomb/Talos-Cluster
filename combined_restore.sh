#!/bin/bash
set -euo pipefail

REFERENCE_COMMIT="7bd6e4e2"
BACKUP_DIR="$HOME/dev/combined-restore-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "=== Helm-Release Enhancement (ref: $REFERENCE_COMMIT) ==="
echo "Backups at: $BACKUP_DIR"

if [ ! -d ".git" ]; then
  echo "❌ Not a git repo!" && exit 1
fi

HELM_FILES=$(find . -name "helm-release.yaml" -type f ! -path "$BACKUP_DIR/*" ! -name "*backup*" | sort)

# Temp files
TMP_CUR=$(mktemp) TMP_REF=$(mktemp) TMP_MERGE=$(mktemp) TMP_BLOCK=$(mktemp)
trap 'rm -f "$TMP_CUR" "$TMP_REF" "$TMP_MERGE" "$TMP_BLOCK"' EXIT

for file in $HELM_FILES; do
  echo "🔍 Processing: $file"
  cp "$file" "$BACKUP_DIR/$(basename "$(dirname "$file")")-helm-release.backup"
  
  if ! git show "$REFERENCE_COMMIT:$file" &>/dev/null; then
    echo "  ℹ️ No reference version, skipping"
    continue
  fi

  yq e '.spec.values // {}' "$file" > "$TMP_CUR"
  git show "$REFERENCE_COMMIT:$file" | yq e '.spec.values // {}' - > "$TMP_REF"
  cp "$TMP_CUR" "$TMP_MERGE"
  MOD=false

  # Shallow merge to $TMP_MERGE
  yq eval-all '. as $item ireduce ({}; . * $item )' "$TMP_CUR" "$TMP_REF" > "$TMP_MERGE"

  # workload.main
  if [ "$(yq e '.workload.main // ""' "$TMP_MERGE")" = "" ]; then
    echo "  ➕ Adding workload.main"
    yq e '.workload.main' "$TMP_REF" > "$TMP_BLOCK"
    yq e '.workload.main = load("'"$TMP_BLOCK"'")' -i "$TMP_MERGE"
    MOD=true
  else
    echo "  ✔️ workload.main block present"
  fi

  # podOptions.hostUsers
  if [ "$(yq e '.podOptions.hostUsers // false' "$TMP_MERGE")" != "true" ]; then
    echo "  ➕ Adding podOptions.hostUsers: true"
    yq e '.podOptions.hostUsers = true' -i "$TMP_MERGE"
    MOD=true
  else
    echo "  ✔️ podOptions.hostUsers: true present"
  fi

  # Add service if env vars found in reference
  if yq e 'tostring | test("\\$\\{.*\\}")' "$TMP_REF" | grep -q true; then
    if [ "$(yq e '.service // ""' "$TMP_MERGE")" = "" ]; then
      echo "  ➕ Adding service (env detected)"
      yq e '.service' "$TMP_REF" > "$TMP_BLOCK"
      yq e '.service = load("'"$TMP_BLOCK"'")' -i "$TMP_MERGE"
      MOD=true
    fi
  fi

  # Add ingress if nginx is mentioned
  if yq e '.ingress | tostring | test("nginx")' "$TMP_REF" | grep -q true; then
    if [ "$(yq e '.ingress // ""' "$TMP_MERGE")" = "" ]; then
      echo "  ➕ Adding ingress (nginx detected)"
      yq e '.ingress' "$TMP_REF" > "$TMP_BLOCK"
      yq e '.ingress = load("'"$TMP_BLOCK"'")' -i "$TMP_MERGE"
      MOD=true
    fi
  fi

  # Apply merged values *into* existing .spec.values (deep merge)
  echo "  🔄 Merging changes into helm-release.yaml"
  yq eval-all --inplace '.spec.values *= load("'"$TMP_MERGE"'")' "$file"
  echo "  ✅ Updated"
done

echo ""
echo "🎉 Done! All enhanced files are backed up in: $BACKUP_DIR"
