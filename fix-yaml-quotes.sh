#!/bin/bash

# Script to fix YAML quote positioning for hostname patterns
# Changes: host: "service.${BASE_DOMAIN}" 
# To:      host: service."${BASE_DOMAIN}"

set -e

SEARCH_DIR="${1:-.}"
echo "Fixing YAML quote positioning in: $SEARCH_DIR"

TOTAL_FILES=0
MODIFIED_FILES=0

# Find all YAML files
for file in $(find "$SEARCH_DIR" -name "*.yaml" -o -name "*.yml"); do
    
    # Skip if no HOST patterns to fix
    if ! grep -q 'host: ".*\${.*}"' "$file" 2>/dev/null; then
        continue
    fi
    
    TOTAL_FILES=$((TOTAL_FILES + 1))
    echo "Processing: $file"
    
    # Create backup
    cp "$file" "$file.backup"
    
    # Fix the quote positioning patterns
    
    # Pattern 1: host: "service.${BASE_DOMAIN}" -> host: service."${BASE_DOMAIN}"
    sed -i 's/host: "\([^"]*\)\.\(\${[^}]*}\)"/host: \1."\2"/g' "$file"
    
    # Pattern 2: host: service.${BASE_DOMAIN}" -> host: service."${BASE_DOMAIN}"
    sed -i 's/host: \([^"]*\)\.\(\${[^}]*}\)"/host: \1."\2"/g' "$file"
    
    # Pattern 3: host: service.${BASE_DOMAIN}"" -> host: service."${BASE_DOMAIN}"
    sed -i 's/host: \([^"]*\)\.\(\${[^}]*}\)""/host: \1."\2"/g' "$file"
    
    # Pattern 4: host: service."${BASE_DOMAIN}"" -> host: service."${BASE_DOMAIN}"
    sed -i 's/host: \([^"]*\)\."\(\${[^}]*}\)""/host: \1."\2"/g' "$file"
    
    # Pattern 5: Fix any hosts section patterns too
    sed -i 's/- host: "\([^"]*\)\.\(\${[^}]*}\)"/- host: \1."\2"/g' "$file"
    sed -i 's/- host: \([^"]*\)\.\(\${[^}]*}\)"/- host: \1."\2"/g' "$file"
    sed -i 's/- host: \([^"]*\)\.\(\${[^}]*}\)""/- host: \1."\2"/g' "$file"
    sed -i 's/- host: \([^"]*\)\."\(\${[^}]*}\)""/- host: \1."\2"/g' "$file"
    
    # Pattern 6: Fix TLS hosts section patterns
    sed -i 's/hosts: \["\([^"]*\)\.\(\${[^}]*}\)"\]/hosts: [\1."\2"]/g' "$file"
    sed -i 's/hosts: \[\([^"]*\)\.\(\${[^}]*}\)"\]/hosts: [\1."\2"]/g' "$file"
    sed -i 's/hosts: \[\([^"]*\)\.\(\${[^}]*}\)""\]/hosts: [\1."\2"]/g' "$file"
    
    # Check if changes were made
    if ! cmp -s "$file" "$file.backup"; then
        MODIFIED_FILES=$((MODIFIED_FILES + 1))
        echo "  ✓ Fixed quote positioning"
        
        # Show what changed
        echo "  Changes:"
        diff -u "$file.backup" "$file" | grep "^[+-]" | head -5
    else
        echo "  - No changes needed"
        rm -f "$file.backup"
    fi
done

echo ""
echo "Summary:"
echo "- Files processed: $TOTAL_FILES" 
echo "- Files modified: $MODIFIED_FILES"

if [[ $MODIFIED_FILES -gt 0 ]]; then
    echo ""
    echo "Next steps:"
    echo "1. Review the changes in .backup files"
    echo "2. Apply changes: flux reconcile kustomization --with-source"
    echo "3. Clean up: find $SEARCH_DIR -name '*.backup' -delete"
fi
