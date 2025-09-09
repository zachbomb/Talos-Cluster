#!/bin/bash
set -euo pipefail

BACKUP_DIR="$HOME/dev/cleanup-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "=== Cleaning up previous script modifications ==="
echo "Backups at: $BACKUP_DIR"

if [ ! -d ".git" ]; then
  echo "❌ Not a git repo!" && exit 1
fi

HELM_FILES=$(find . -name "helm-release.yaml" -type f ! -path "$BACKUP_DIR/*" ! -name "*backup*" | sort)

# Apps that legitimately need hostUsers
NEEDS_HOST_USERS=("volsync" "longhorn" "nvidia-device-plugin" "metallb" "cilium" "traefik" "intel-device-plugin-operator" "intel-device-plugin-gpu")

# Function to check if chart is TrueCharts
is_truecharts() {
  local file="$1"
  yq e '.spec.chart.spec.sourceRef.name' "$file" | grep -q "truecharts"
}

# Function to check if app needs hostUsers
needs_host_users() {
  local app_name="$1"
  for needed_app in "${NEEDS_HOST_USERS[@]}"; do
    if [[ "$app_name" == *"$needed_app"* ]]; then
      return 0
    fi
  done
  return 1
}

for file in $HELM_FILES; do
  echo "🔍 Processing: $file"
  cp "$file" "$BACKUP_DIR/$(basename "$(dirname "$file")")-helm-release.backup"
  
  APP_NAME=$(yq e '.metadata.name' "$file")
  NAMESPACE=$(yq e '.metadata.namespace' "$file")
  MOD=false
  
  echo "  📋 App: $APP_NAME, Namespace: $NAMESPACE"
  
  # Check current hostUsers setting
  CURRENT_HOST_USERS=$(yq e '.spec.values.podOptions.hostUsers // false' "$file")
  
  if [ "$CURRENT_HOST_USERS" = "true" ]; then
    if needs_host_users "$file"; then
      echo "  ✔️ Keeping podOptions.hostUsers: true (required for chart: $(yq e '.spec.chart.spec.chart' "$file"))"
    else
      echo "  🔄 Removing unnecessary podOptions.hostUsers from $APP_NAME"
      yq e 'del(.spec.values.podOptions.hostUsers)' -i "$file"
      
      # If podOptions is now empty, remove it entirely
      if [ "$(yq e '.spec.values.podOptions | length' "$file")" = "0" ]; then
        yq e 'del(.spec.values.podOptions)' -i "$file"
      fi
      
      MOD=true
    fi
  fi
  
  # Check for conflicting workload configurations
  WORKLOAD_HOST_USERS=$(yq e '.spec.values.workload.main.podSpec.hostUsers // ""' "$file")
  POD_OPTIONS_HOST_USERS=$(yq e '.spec.values.podOptions.hostUsers // ""' "$file")
  
  if [ "$WORKLOAD_HOST_USERS" != "" ] && [ "$POD_OPTIONS_HOST_USERS" != "" ]; then
    if [ "$WORKLOAD_HOST_USERS" != "$POD_OPTIONS_HOST_USERS" ]; then
      echo "  ⚠️ Conflicting hostUsers settings detected"
      echo "     podOptions: $POD_OPTIONS_HOST_USERS, workload: $WORKLOAD_HOST_USERS"
      
      if is_truecharts "$file"; then
        echo "  🔄 Removing workload.main.podSpec.hostUsers (using podOptions instead)"
        yq e 'del(.spec.values.workload.main.podSpec.hostUsers)' -i "$file"
        MOD=true
      fi
    fi
  fi
  
  # Check for TrueCharts-specific configs in non-TrueCharts apps
  if ! is_truecharts "$file"; then
    if [ "$(yq e '.spec.values.podOptions // ""' "$file")" != "" ]; then
      echo "  🔄 Removing TrueCharts-specific podOptions from official chart"
      yq e 'del(.spec.values.podOptions)' -i "$file"
      MOD=true
    fi
    
    if [ "$(yq e '.spec.values.workload.main // ""' "$file")" != "" ]; then
      WORKLOAD_CONTENT=$(yq e '.spec.values.workload.main' "$file")
      if [[ "$WORKLOAD_CONTENT" == *"podSpec"* ]]; then
        echo "  🔄 Removing TrueCharts-specific workload config from official chart"
        yq e 'del(.spec.values.workload)' -i "$file"
        MOD=true
      fi
    fi
  fi
  
  if [ "$MOD" = true ]; then
    echo "  ✅ Cleaned up"
  else
    echo "  ➖ No cleanup needed"
  fi
done

echo ""
echo "🎉 Cleanup complete! Backups at: $BACKUP_DIR"
echo ""
echo "📝 Next steps:"
echo "   1. Review changes: git diff"
echo "   2. Test critical applications first"
echo "   3. Check for Pod Security Standard violations"
echo "   4. Run: kubectl get pods -A | grep -E '(Error|CrashLoop)'"