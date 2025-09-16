#!/bin/bash

# Revert to Staging Certificates Script
# Switches certificates back from production to staging for immediate functionality

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

main() {
    log "Starting Certificate Revert to Staging Process"
    
    # Check if we're in the right directory
    if [[ ! -f "./clustertool" ]] || [[ ! -d "clusters/main" ]]; then
        error "Script must be run from the root of your cluster repository"
    fi
    
    # Step 1: Git pull to ensure we have latest changes
    log "Step 1: Updating repository with latest changes"
    git fetch origin
    
    if ! git diff --quiet HEAD origin/$BRANCH; then
        log "Repository has remote changes, pulling..."
        git pull origin $BRANCH
    else
        log "Repository is up to date"
    fi
    
    # Step 2: Find and update all helm releases with production certificates back to staging
    log "Step 2: Reverting certificates from production back to staging"
    
    updated_files=()
    
    while IFS= read -r -d '' file; do
        if grep -q "wethecommon-prod-cert" "$file"; then
            log "  Reverting $(echo "$file" | sed "s|$CLUSTER_PATH/apps/||" | sed 's|/app/helm-release.yaml||') back to staging"
            sed -i.bak 's/wethecommon-prod-cert/wethecommon-staging-cert/g' "$file"
            rm -f "$file.bak"
            updated_files+=("$file")
        fi
    done < <(find "$CLUSTER_PATH/apps" -name "helm-release.yaml" -type f -print0)
    
    log "Reverted ${#updated_files[@]} helm-release.yaml file(s) back to staging certificates"
    
    if [[ ${#updated_files[@]} -eq 0 ]]; then
        warn "No helm-release.yaml files contained production certificates. All may already be using staging certificates."
        exit 0
    fi
    
    # Show which files were reverted
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
    git commit -m "Revert certificates back to staging - avoiding production rate limits"
    
    log "Step 5: Pushing changes to repository"
    git push origin $BRANCH
    
    # Step 6: Reconcile Flux
    log "Step 6: Reconciling Flux to apply changes"
    flux reconcile source git cluster
    flux reconcile kustomization flux-entry
    
    log "Certificate revert completed successfully!"
    log "All services should now be using staging Let's Encrypt certificates with immediate functionality."
    log "You can switch back to production certificates this evening using the corrected script."
    
    # Show certificate status
    log "Current certificate status:"
    kubectl get certificates -A | grep -E "(NAMESPACE|False)" || echo "All certificates appear to be ready!"
    
    log "Services should be accessible with valid SSL (staging) certificates shortly."
    log "Remember to clear HSTS for any domains if needed: chrome://net-internals/#hsts"
}

# Run main function
main "$@"
