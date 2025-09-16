#!/bin/bash

# Selective Certificate Management Script
# Keeps only rate-limited services on staging, moves everything else to production

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
    log "Starting Selective Certificate Configuration"
    
    # Check if we're in the right directory
    if [[ ! -f "./clustertool" ]] || [[ ! -d "clusters/main" ]]; then
        error "Script must be run from the root of your cluster repository"
    fi
    
    # Services that should stay on staging (rate limited until tonight)
    declare -a staging_services=(
        "home/tandoor-recipes"
        "media/notifiarr"
        "media/nzbget"
        "media/plex"
        "media/readarr"
        "media/sabnzbd"
        "media/sonarr"
        "media/tautulli"
        "media/tinymediamanager"
        "media/tunarr"
        "ollama"
        "media/roon"
        "media/overseerr"
        "media/bazarr"
        "media/prowlarr"
        "media/dizquetv"
        "media/emby"
        "media/radarr"
        "code-server"
    )
    
    # Add minio if it exists (it's in networking namespace)
    if [[ -f "$CLUSTER_PATH/apps/networking/minio/app/helm-release.yaml" ]]; then
        staging_services+=("networking/minio")
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
    
    # Step 2: Function to check if service should be on staging
    log "Step 2: Processing certificate configurations"
    
    is_staging_service() {
        local service="$1"
        for staging_service in "${staging_services[@]}"; do
            if [[ "$service" == "$staging_service" ]]; then
                return 0  # Found in staging list
            fi
        done
        return 1  # Not found in staging list
    }
    
    updated_to_prod=0
    kept_staging=0
    
    # Step 3: Process all helm-release.yaml files
    while IFS= read -r -d '' file; do
        # Extract service path from file path
        service_path=$(echo "$file" | sed "s|$CLUSTER_PATH/apps/||" | sed 's|/app/helm-release.yaml||')
        
        if is_staging_service "$service_path"; then
            # This service should stay on staging
            if grep -q "wethecommon-prod-cert" "$file"; then
                log "  Switching $service_path to staging (rate limited)"
                sed -i.bak 's/wethecommon-prod-cert/wethecommon-staging-cert/g' "$file"
                rm -f "$file.bak"
            else
                log "  Keeping $service_path on staging"
            fi
            kept_staging=$((kept_staging + 1))
        else
            # This service should be on production
            if grep -q "wethecommon-staging-cert" "$file"; then
                log "  Switching $service_path to production (no rate limits)"
                sed -i.bak 's/wethecommon-staging-cert/wethecommon-prod-cert/g' "$file"
                rm -f "$file.bak"
                updated_to_prod=$((updated_to_prod + 1))
            fi
        fi
    done < <(find "$CLUSTER_PATH/apps" -name "helm-release.yaml" -type f -print0)
    
    log "Summary:"
    log "  - $kept_staging services kept on staging certificates"
    log "  - $updated_to_prod services switched to production certificates"
    
    # Step 4: Generate cluster configuration
    log "Step 3: Generating cluster configuration"
    ./clustertool genconfig
    
    # Step 5: Commit and push changes
    log "Step 4: Committing changes to git"
    git add -A
    git commit -m "Selective certificate config: staging for rate-limited services, production for others"
    
    log "Step 5: Pushing changes to repository"
    git push origin $BRANCH
    
    # Step 6: Reconcile Flux
    log "Step 6: Reconciling Flux to apply changes"
    flux reconcile source git cluster
    flux reconcile kustomization flux-entry
    
    log "Selective certificate configuration completed successfully!"
    log "Rate-limited services remain on staging, others moved to production."
    log "Tonight you can switch all remaining staging services to production."
    
    # Show current status
    log "Current certificate status:"
    kubectl get certificates -A | grep -E "(NAMESPACE|False)" || echo "All certificates appear to be ready!"
}

# Run main function
main "$@"