#!/bin/bash

# Certificate Production Switch Script
# Switches certificates from staging back to production after rate limits expire
# Run after September 17, 2025 01:00 UTC (September 16, 2025 5:00 PM PST)

set -euo pipefail

# Configuration
REPO_DIR="$(pwd)"
CLUSTER_PATH="clusters/main/kubernetes"
BRANCH="main"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
    exit 1
}

check_time() {
    local target_time="2025-09-17 01:00:00 UTC"
    local current_time=$(date -u +"%Y-%m-%d %H:%M:%S")
    local target_epoch=$(date -d "$target_time" +%s 2>/dev/null || date -j -f "%Y-%m-%d %H:%M:%S %Z" "$target_time" +%s)
    local current_epoch=$(date -u +%s)
    
    if [ "$current_epoch" -lt "$target_epoch" ]; then
        error "Current time ($current_time UTC) is before safe switch time ($target_time). Please wait."
    fi
    
    log "Time check passed. Safe to proceed with certificate switch."
}

update_helm_release() {
    local file="$1"
    local service_name=$(basename $(dirname $(dirname "$file")))
    
    log "Processing $service_name..."
    
    # Replace staging cert issuer with production cert issuer
    if grep -q "wethecommon-staging-cert" "$file"; then
        sed -i.bak 's/wethecommon-staging-cert/wethecommon-prod-cert/g' "$file"
        log "  Updated issuer from staging to production"
        rm -f "$file.bak"
        return 0
    else
        warn "  No staging certificate reference found in $file"
        return 1
    fi
}

main() {
    log "Starting Certificate Production Switch Process"
    
    # Check if we're in the right directory
    if [[ ! -f "./clustertool" ]] || [[ ! -d "clusters/main" ]]; then
        error "Script must be run from the root of your cluster repository"
    fi
    
    # Check if it's safe to proceed
    check_time
    
    # Step 1: Git pull to ensure we have latest changes
    log "Step 1: Updating repository with latest changes"
    git fetch origin
    
    if ! git diff --quiet HEAD origin/$BRANCH; then
        log "Repository has remote changes, pulling..."
        git pull origin $BRANCH
    else
        log "Repository is up to date"
    fi
    
    # Step 2: Find and update all helm releases with staging certificates
    log "Step 2: Switching certificates from staging to production"
    
    # Find all helm-release.yaml files and replace staging with production certificates
    updated_files=()
    
    while IFS= read -r -d '' file; do
        if grep -q "wethecommon-staging-cert" "$file"; then
            log "  Updating $(echo "$file" | sed "s|$CLUSTER_PATH/apps/||" | sed 's|/app/helm-release.yaml||')"
            sed -i.bak 's/wethecommon-staging-cert/wethecommon-prod-cert/g' "$file"
            rm -f "$file.bak"
            updated_files+=("$file")
        fi
    done < <(find "$CLUSTER_PATH/apps" -name "helm-release.yaml" -type f -print0)
    
    log "Updated ${#updated_files[@]} helm-release.yaml file(s) to use production certificates"
    
    if [[ ${#updated_files[@]} -eq 0 ]]; then
        warn "No helm-release.yaml files contained staging certificates. All may already be using production certificates."
        exit 0
    fi
    
    # Show which files were updated
    for file in "${updated_files[@]}"; do
        service_path=$(echo "$file" | sed "s|$CLUSTER_PATH/apps/||" | sed 's|/app/helm-release.yaml||')
        log "  ✓ $service_path"
    done
    
    # Step 3: Generate cluster configuration
    log "Step 3: Generating cluster configuration"
    ./clustertool genconfig
    
    # Step 4: Commit and push changes
    log "Step 4: Committing changes to git"
    git add -A
    git commit -m "Switch certificates from staging to production after rate limit expiry"
    
    log "Step 5: Pushing changes to repository"
    git push origin $BRANCH
    
    # Step 6: Reconcile Flux
    log "Step 6: Reconciling Flux to apply changes"
    flux reconcile source git cluster
    flux reconcile kustomization flux-entry
    
    log "Certificate switch completed successfully!"
    log "All services should now be using production Let's Encrypt certificates."
    log "Monitor certificate status with: kubectl get certificates -A"
    
    # Optional: Show certificate status
    log "Current certificate status:"
    kubectl get certificates -A | grep -E "(NAMESPACE|False)" || echo "All certificates appear to be ready!"
}

# Run main function
main "$@"