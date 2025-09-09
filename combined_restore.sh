#!/bin/bash

# Combined Longhorn and Helm-Release Configuration Enhancement Script
# Uses 7bd6e4e2 as reference to enhance current 0dba0503 configurations

REFERENCE_COMMIT="7bd6e4e2"
BACKUP_DIR="$HOME/combined-restore-backup-$(date +%Y%m%d-%H%M%S)"
MODIFIED_FILES_LIST=""

echo "=== Combined Longhorn & Helm-Release Enhancement ==="
echo "Using reference commit: $REFERENCE_COMMIT"
echo "Creating backup directory: $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

# Verify we're in the right git repository
if [ ! -d ".git" ]; then
    echo "❌ Error: Not in a git repository. Run this from your Talos-Cluster root."
    exit 1
fi

echo "📍 Working in: $(pwd)"
echo ""

# =====================================
# PART 1: Restore Longhorn Files
# =====================================
echo "=== PART 1: Restoring Longhorn Files ==="

LONGHORN_FILES=(
    "clusters/main/kubernetes/system/longhorn/app/ingress.yaml"
    "clusters/main/kubernetes/system/longhorn/app/jobs/kustomization.yaml"
    "clusters/main/kubernetes/system/longhorn/app/jobs/snapshot-cleanup.yaml"
    "clusters/main/kubernetes/system/longhorn/app/jobs/snapshot-delete.yaml"
    "clusters/main/kubernetes/system/longhorn/app/jobs/trim.yaml"
)

LONGHORN_RESTORED=0

for file in "${LONGHORN_FILES[@]}"; do
    echo "Restoring: $file"
    
    # Backup current version if it exists
    if [ -f "$file" ]; then
        cp "$file" "$BACKUP_DIR/$(basename "$file").current"
    fi
    
    # Create directory if it doesn't exist
    mkdir -p "$(dirname "$file")"
    
    # Restore from reference commit
    if git show "$REFERENCE_COMMIT:$file" > "$file" 2>/dev/null; then
        echo "  ✅ Restored from commit $REFERENCE_COMMIT"
        LONGHORN_RESTORED=$((LONGHORN_RESTORED + 1))
    else
        echo "  ❌ Failed to restore - file not found in commit $REFERENCE_COMMIT"
    fi
done

echo "Longhorn files restored: $LONGHORN_RESTORED/${#LONGHORN_FILES[@]}"
echo ""

# =====================================
# PART 2: Enhance Helm-Release Files
# =====================================
echo "=== PART 2: Enhancing Helm-Release Configurations ==="

# Find all helm-release.yaml files
HELM_FILES=$(find . -name "helm-release.yaml" -type f | grep -v backup | grep -v "$BACKUP_DIR" | sort)
TOTAL_HELM_FILES=$(echo "$HELM_FILES" | wc -l)
HELM_MODIFIED_COUNT=0

if [ -z "$HELM_FILES" ]; then
    echo "No helm-release.yaml files found"
else
    echo "Found $TOTAL_HELM_FILES helm-release.yaml files"
    echo ""

    for file in $HELM_FILES; do
        echo "Processing: $file"
        MODIFIED=false
        
        # Always backup first
        APP_NAME=$(basename "$(dirname "$file")")
        cp "$file" "$BACKUP_DIR/${APP_NAME}-helm-release.yaml.current"
        
        # Check if reference commit has this file
        if ! git show "$REFERENCE_COMMIT:$file" >/dev/null 2>&1; then
            echo "  ℹ️  File not in reference commit - skipping"
            continue
        fi
        
        # 1. Handle missing values section - copy entire values section from reference
        if ! grep -q "values:" "$file"; then
            echo "  ⚠️  No values section found - copying from reference commit"
            
            # Extract values section from reference commit
            git show "$REFERENCE_COMMIT:$file" | awk '/^[[:space:]]*values:[[:space:]]*$/{flag=1} flag && /^[[:space:]]*[a-zA-Z]/ && !/^[[:space:]]*values:/ && !/^[[:space:]]*#/{if(indent==""){indent=match($0,/[^ ]/)} if(match($0,/[^ ]/) <= indent && NR>start){flag=0}} flag{if(/^[[:space:]]*values:[[:space:]]*$/){start=NR} print}' > /tmp/ref_values
            
            if [ -s /tmp/ref_values ]; then
                # Append values section to current file
                cat /tmp/ref_values >> "$file"
                echo "  ✅ Added values section from reference commit"
                MODIFIED=true
            fi
            rm -f /tmp/ref_values
        else
            # 2. Check if reference has workload.main that current doesn't
            REF_HAS_WORKLOAD=$(git show "$REFERENCE_COMMIT:$file" | grep -A 5 "workload:" | grep -c "main:")
            CURRENT_HAS_WORKLOAD=$(grep -A 5 "workload:" "$file" 2>/dev/null | grep -c "main:")
            
            if [ "$REF_HAS_WORKLOAD" -gt 0 ] && [ "$CURRENT_HAS_WORKLOAD" -eq 0 ]; then
                echo "  ⚠️  Reference has workload.main, current doesn't - adding standard resources"
                # Add standard workload.main resources
                awk '
                /^[[:space:]]*values:[[:space:]]*$/ { 
                    print
                    print "    workload:"
                    print "      main:"
                    print "        autoscaling:"
                    print "          vpa:"
                    print "            enabled: true"
                    print "        resources:"
                    print "          requests:"
                    print "            memory: 1024Mi"
                    print "            cpu: 50m"
                    print "          limits:"
                    print "            memory: 2Gi"
                    print "            cpu: 500m"
                    next 
                } 
                { print }
                ' "$file" > "$file.tmp" && mv "$file.tmp" "$file"
                echo "  ✅ Added workload.main resources"
                MODIFIED=true
            else
                echo "  ✅ workload.main configuration is appropriate"
            fi
            
            # 3. Check if reference has podOptions.hostUsers that current doesn't
            REF_HAS_PODOPTIONS=$(git show "$REFERENCE_COMMIT:$file" | grep -A 3 "podOptions:" | grep -c "hostUsers: true")
            CURRENT_HAS_PODOPTIONS=$(grep -A 3 "podOptions:" "$file" 2>/dev/null | grep -c "hostUsers: true")
            
            if [ "$REF_HAS_PODOPTIONS" -gt 0 ] && [ "$CURRENT_HAS_PODOPTIONS" -eq 0 ]; then
                echo "  ⚠️  Reference has podOptions.hostUsers, current doesn't - adding"
                if grep -q "podOptions:" "$file"; then
                    # Add hostUsers to existing podOptions
                    awk '/podOptions:/ { print; print "              hostUsers: true"; next } { print }' "$file" > "$file.tmp" && mv "$file.tmp" "$file"
                    echo "  ✅ Added hostUsers to existing podOptions"
                else
                    # Add complete podOptions section
                    awk '/^[[:space:]]*values:[[:space:]]*$/ { print; print "        podOptions:"; print "          hostUsers: true"; next } { print }' "$file" > "$file.tmp" && mv "$file.tmp" "$file"
                    echo "  ✅ Added complete podOptions section"
                fi
                MODIFIED=true
            fi
        fi
        
        if [ "$MODIFIED" = true ]; then
            HELM_MODIFIED_COUNT=$((HELM_MODIFIED_COUNT + 1))
            # Add to modified files list
            if [ -z "$MODIFIED_FILES_LIST" ]; then
                MODIFIED_FILES_LIST="$file"
            else
                MODIFIED_FILES_LIST="$MODIFIED_FILES_LIST
$file"
            fi
            echo "  ✅ File enhanced"
        else
            echo "  → No enhancements needed"
        fi
        echo ""
    done
fi

# =====================================
# SUMMARY
# =====================================
echo "=== ENHANCEMENT SUMMARY ==="
echo "Longhorn files restored: $LONGHORN_RESTORED/${#LONGHORN_FILES[@]}"
echo "Helm-release files processed: $TOTAL_HELM_FILES"
echo "Helm-release files enhanced: $HELM_MODIFIED_COUNT"
echo "All backups saved to: $BACKUP_DIR"
echo ""

# Verify Longhorn files have content
echo "=== Longhorn File Verification ==="
for file in "${LONGHORN_FILES[@]}"; do
    if [ -f "$file" ] && [ -s "$file" ]; then
        echo "✅ $file ($(wc -l < "$file") lines)"
    else
        echo "❌ $file (empty or missing)"
    fi
done

echo ""
echo "=== Enhanced Helm-Release Files ==="
if [ -n "$MODIFIED_FILES_LIST" ]; then
    echo "$MODIFIED_FILES_LIST" | while IFS= read -r file; do
        if [ -n "$file" ]; then
            echo "✅ $file"
        fi
    done
else
    echo "No helm-release files were enhanced"
fi

echo ""
echo "=== Next Steps ==="
echo "1. Review changes: git status"
echo "2. Check specific files: git diff <filename>"
echo "3. Test Longhorn ingress: head -n 5 clusters/main/kubernetes/system/longhorn/app/ingress.yaml"
echo "4. Commit when ready: git add . && git commit -m 'Enhance configurations using reference commit $REFERENCE_COMMIT'"
echo ""
echo "Script completed successfully!"