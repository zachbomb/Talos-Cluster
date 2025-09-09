#!/bin/bash
set -euo pipefail

REFERENCE_COMMIT="7bd6e4e2"
BACKUP_DIR="$HOME/dev/cleanup-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "=== Cleaning up previous script modifications ==="
echo "Backups at: $BACKUP_DIR"

if [ ! -d ".git" ]; then
  echo "❌ Not a git repo!" && exit 1
fi

HELM_FILES=$(find . -name "helm-release.yaml" -type f ! -path "$BACKUP_DIR/*" ! -name "*backup*" | sort)

# Temp files
TMP_REF=$(mktemp)
trap 'rm -f "$TMP_REF" "${TMP_REF}".service "${TMP_REF}".ingress' EXIT

# Function to check if chart is TrueCharts
is_truecharts() {
  local file="$1"
  yq e '.spec.chart.spec.sourceRef.name' "$file" | grep -q "truecharts"
}

for file in $HELM_FILES; do
  echo "🔍 Processing: $file"
  cp "$file" "$BACKUP_DIR/$(basename "$(dirname "$file")")-helm-release.backup"
  
  APP_NAME=$(yq e '.metadata.name' "$file")
  NAMESPACE=$(yq e '.metadata.namespace' "$file")
  MOD=false
  
  echo "  📋 App: $APP_NAME, Namespace: $NAMESPACE"
  
  # Check if reference version exists
  if ! git show "$REFERENCE_COMMIT:$file" &>/dev/null; then
    echo "  ℹ️ No reference version, cleaning current config"
    
    # Remove hostUsers since there's no reference to compare against
    if [ "$(yq e '.spec.values.podOptions.hostUsers // false' "$file")" = "true" ]; then
      echo "  🔄 Removing podOptions.hostUsers (no reference found)"
      yq e 'del(.spec.values.podOptions.hostUsers)' -i "$file"
      
      # Clean up empty podOptions
      if [ "$(yq e '.spec.values.podOptions | length' "$file" 2>/dev/null || echo "0")" = "0" ]; then
        yq e 'del(.spec.values.podOptions)' -i "$file"
      fi
      MOD=true
    fi
    
    # Remove empty workload.main
    WORKLOAD_MAIN=$(yq e '.spec.values.workload.main // ""' "$file")
    if [ "$WORKLOAD_MAIN" = "null" ] || [ "$WORKLOAD_MAIN" = "" ]; then
      echo "  🔄 Removing empty workload.main block"
      yq e 'del(.spec.values.workload.main)' -i "$file"
      MOD=true
      
      if [ "$(yq e '.spec.values.workload | length' "$file" 2>/dev/null || echo "0")" = "0" ]; then
        yq e 'del(.spec.values.workload)' -i "$file"
      fi
    fi
    
    if [ "$MOD" = true ]; then
      echo "  ✅ Cleaned up"
    else
      echo "  ➖ No cleanup needed"
    fi
    continue
  fi
  
  # Extract reference values
  git show "$REFERENCE_COMMIT:$file" | yq e '.spec.values // {}' - > "$TMP_REF"
  
  # Check what hostUsers config exists in reference
  REF_POD_OPTIONS_HOST_USERS=$(yq e '.podOptions.hostUsers // false' "$TMP_REF")
  REF_WORKLOAD_HOST_USERS=$(yq e '.workload.main.podSpec.hostUsers // false' "$TMP_REF")
  
  # Check current config
  CURRENT_POD_OPTIONS_HOST_USERS=$(yq e '.spec.values.podOptions.hostUsers // false' "$file")
  CURRENT_WORKLOAD_HOST_USERS=$(yq e '.spec.values.workload.main.podSpec.hostUsers // false' "$file")
  
  # Handle podOptions.hostUsers based on reference
  if [ "$REF_POD_OPTIONS_HOST_USERS" = "true" ]; then
    if [ "$CURRENT_POD_OPTIONS_HOST_USERS" != "true" ]; then
      echo "  ➕ Adding podOptions.hostUsers: true (found in reference)"
      yq e '.spec.values.podOptions.hostUsers = true' -i "$file"
      MOD=true
    else
      echo "  ✔️ Keeping podOptions.hostUsers: true (matches reference)"
    fi
  else
    if [ "$CURRENT_POD_OPTIONS_HOST_USERS" = "true" ]; then
      echo "  🔄 Removing podOptions.hostUsers (not in reference)"
      yq e 'del(.spec.values.podOptions.hostUsers)' -i "$file"
      
      # Clean up empty podOptions
      if [ "$(yq e '.spec.values.podOptions | length' "$file" 2>/dev/null || echo "0")" = "0" ]; then
        yq e 'del(.spec.values.podOptions)' -i "$file"
      fi
      MOD=true
    fi
  fi
  
  # Handle workload.main.podSpec.hostUsers based on reference
  if [ "$REF_WORKLOAD_HOST_USERS" = "true" ]; then
    if [ "$CURRENT_WORKLOAD_HOST_USERS" != "true" ]; then
      echo "  ➕ Adding workload.main.podSpec.hostUsers: true (found in reference)"
      yq e '.spec.values.workload.main.enabled = true' -i "$file"
      yq e '.spec.values.workload.main.podSpec.hostUsers = true' -i "$file"
      MOD=true
    else
      echo "  ✔️ Keeping workload.main.podSpec.hostUsers: true (matches reference)"
    fi
  else
    if [ "$CURRENT_WORKLOAD_HOST_USERS" = "true" ]; then
      echo "  🔄 Removing workload.main.podSpec.hostUsers (not in reference)"
      yq e 'del(.spec.values.workload.main.podSpec.hostUsers)' -i "$file"
      MOD=true
    fi
  fi
  
  # Handle service configuration based on env vars in reference
  REF_HAS_ENV_VARS=$(yq e 'tostring | test("\\$\\{.*\\}")' "$TMP_REF" && echo "true" || echo "false")
  REF_HAS_SERVICE=$(yq e '.service // ""' "$TMP_REF")
  CURRENT_HAS_SERVICE=$(yq e '.spec.values.service // ""' "$file")
  
  if [ "$REF_HAS_ENV_VARS" = "true" ] || [ "$REF_HAS_SERVICE" != "" ]; then
    if [ "$CURRENT_HAS_SERVICE" = "" ]; then
      if [ "$REF_HAS_SERVICE" != "" ]; then
        echo "  ➕ Adding service configuration (found in reference)"
        yq e '.service' "$TMP_REF" > "${TMP_REF}.service"
        yq e '.spec.values.service = load("'"${TMP_REF}.service"'")' -i "$file"
        rm -f "${TMP_REF}.service"
        MOD=true
      else
        echo "  ➕ Service needed (env vars detected in reference) but no service block found"
        echo "      Skipping - requires manual service configuration"
      fi
    else
      echo "  ✔️ Service configuration present"
    fi
  else
    if [ "$CURRENT_HAS_SERVICE" != "" ]; then
      echo "  🔄 Removing service configuration (no env vars or service in reference)"
      yq e 'del(.spec.values.service)' -i "$file"
      MOD=true
    fi
  fi
  
  # Handle ingress configuration based on nginx mentions in reference
  REF_HAS_NGINX=$(yq e '.ingress | tostring | test("nginx")' "$TMP_REF" && echo "true" || echo "false")
  REF_HAS_INGRESS=$(yq e '.ingress // ""' "$TMP_REF")
  CURRENT_HAS_INGRESS=$(yq e '.spec.values.ingress // ""' "$file")
  
  if [ "$REF_HAS_NGINX" = "true" ] || [ "$REF_HAS_INGRESS" != "" ]; then
    if [ "$CURRENT_HAS_INGRESS" = "" ]; then
      if [ "$REF_HAS_INGRESS" != "" ]; then
        echo "  ➕ Adding ingress configuration (found in reference)"
        yq e '.ingress' "$TMP_REF" > "${TMP_REF}.ingress"
        yq e '.spec.values.ingress = load("'"${TMP_REF}.ingress"'")' -i "$file"
        rm -f "${TMP_REF}.ingress"
        MOD=true
      else
        echo "  ➕ Ingress needed (nginx detected in reference) but no ingress block found"
        echo "      Skipping - requires manual ingress configuration"
      fi
    else
      echo "  ✔️ Ingress configuration present"
    fi
  else
    if [ "$CURRENT_HAS_INGRESS" != "" ]; then
      echo "  🔄 Removing ingress configuration (no nginx mentions or ingress in reference)"
      yq e 'del(.spec.values.ingress)' -i "$file"
      MOD=true
    fi
  fi
  
  # Clean up empty workload.main
  WORKLOAD_MAIN=$(yq e '.spec.values.workload.main // ""' "$file")
  if [ "$WORKLOAD_MAIN" = "null" ] || [ "$WORKLOAD_MAIN" = "" ]; then
    echo "  🔄 Removing empty workload.main block"
    yq e 'del(.spec.values.workload.main)' -i "$file"
    MOD=true
  fi
  
  # Clean up empty workload
  if [ "$(yq e '.spec.values.workload | length' "$file" 2>/dev/null || echo "0")" = "0" ]; then
    yq e 'del(.spec.values.workload)' -i "$file"
    MOD=true
  fi
  
  # Check for conflicting configurations
  FINAL_POD_OPTIONS=$(yq e '.spec.values.podOptions.hostUsers // false' "$file")
  FINAL_WORKLOAD=$(yq e '.spec.values.workload.main.podSpec.hostUsers // false' "$file")
  
  if [ "$FINAL_POD_OPTIONS" = "true" ] && [ "$FINAL_WORKLOAD" = "true" ]; then
    echo "  ⚠️ Both podOptions and workload hostUsers found - removing workload version"
    yq e 'del(.spec.values.workload.main.podSpec.hostUsers)' -i "$file"
    MOD=true
  fi
  
  # Handle TrueCharts vs official chart cleanup
  if ! is_truecharts "$file"; then
    if [ "$(yq e '.spec.values.podOptions // ""' "$file")" != "" ] && [ "$REF_POD_OPTIONS_HOST_USERS" != "true" ]; then
      echo "  🔄 Removing TrueCharts-specific podOptions from official chart"
      yq e 'del(.spec.values.podOptions)' -i "$file"
      MOD=true
    fi
    
    if [ "$(yq e '.spec.values.workload // ""' "$file")" != "" ] && [ "$REF_WORKLOAD_HOST_USERS" != "true" ]; then
      echo "  🔄 Removing TrueCharts-specific workload from official chart"
      yq e 'del(.spec.values.workload)' -i "$file"
      MOD=true
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
echo "   4. Run: kubectl get pods -A | grep -E '(Error|CrashLoop)'

EOF