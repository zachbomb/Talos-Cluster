#!/bin/bash

# Script to add standardized resource configurations to all helm-release.yaml files

# Resource configuration to add
RESOURCE_CONFIG='
    workload:
      main:
        autoscaling:
          vpa:
            enabled: true
        resources:
          requests:
            memory: 1024Mi
            cpu: 50m
          limits:
            memory: 2Gi
            cpu: 500m'

echo "=== Adding Resource Configurations to Helm Releases ==="
echo ""

# Find all helm-release.yaml files
HELM_FILES=$(find . -name "helm-release.yaml" -type f | grep -v ".backup" | sort)

if [ -z "$HELM_FILES" ]; then
    echo "No helm-release.yaml files found"
    exit 1
fi

echo "Found helm-release.yaml files:"
echo "$HELM_FILES"
echo ""

# Counter for modifications
MODIFIED_COUNT=0
TOTAL_COUNT=0

for file in $HELM_FILES; do
    TOTAL_COUNT=$((TOTAL_COUNT + 1))
    echo "Processing: $file"
    
    # Check if file has values section
    if ! grep -q "values:" "$file"; then
        echo "  ⚠️  No values section found - skipping"
        continue
    fi
    
    # Check if workload.main already exists
    if grep -q "workload:" "$file" && grep -A 5 "workload:" "$file" | grep -q "main:"; then
        echo "  ✅ Already has workload.main configuration"
        continue
    fi
    
    # Backup the file
    cp "$file" "${file}.backup-$(date +%Y%m%d-%H%M%S)"
    
    # Add resource configuration after values section
    # First, find the indentation of the values section
    VALUES_INDENT=$(grep -n "values:" "$file" | head -1 | sed 's/.*values://' | wc -c)
    VALUES_INDENT=$((VALUES_INDENT - 1))
    
    # Create temporary file with the addition
    awk -v config="$RESOURCE_CONFIG" '
    /^[[:space:]]*values:[[:space:]]*$/ {
        print $0
        print config
        next
    }
    { print }
    ' "$file" > "${file}.tmp"
    
    # Replace original file
    mv "${file}.tmp" "$file"
    
    echo "  ✅ Added resource configuration"
    MODIFIED_COUNT=$((MODIFIED_COUNT + 1))
done

echo ""
echo "=== Summary ==="
echo "Total files processed: $TOTAL_COUNT"
echo "Files modified: $MODIFIED_COUNT"
echo "Files skipped: $((TOTAL_COUNT - MODIFIED_COUNT))"

if [ $MODIFIED_COUNT -gt 0 ]; then
    echo ""
    echo "=== Modified Files ==="
    for file in $HELM_FILES; do
        if [ -f "${file}.backup-"* ]; then
            echo "Modified: $file"
            echo "  Backup: $(ls ${file}.backup-* | head -1)"
        fi
    done
    
    echo ""
    echo "=== Next Steps ==="
    echo "1. Review the changes:"
    echo "   git diff --name-only | grep helm-release.yaml"
    echo ""
    echo "2. Check specific files:"
    echo "   git diff <filename>"
    echo ""
    echo "3. Test a few critical components:"
    echo "   kubectl get pods -A | grep -E '(Pending|Error|CrashLoopBackOff)'"
    echo ""
    echo "4. If satisfied, commit:"
    echo "   git add . && git commit -m 'Add standardized resource configurations to all helm releases'"
    echo ""
    echo "5. To rollback a specific file if needed:"
    echo "   cp <file>.backup-* <file>"
fi

echo ""
echo "Resource configuration addition completed!"
