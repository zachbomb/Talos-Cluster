#!/bin/bash
# Simple script to fix YAML quote positioning and remove quotes around variables
set -e
SEARCH_DIR="${1:-.}"
echo "Fixing YAML quote positioning in: $SEARCH_DIR"
TOTAL_FILES=0
MODIFIED_FILES=0
for file in $(find "$SEARCH_DIR" -name "*.yaml" -o -name "*.yml"); do
    
    # Skip if no problematic patterns
    if ! grep -q '\${.*}' "$file" 2>/dev/null; then
        continue
    fi
    
    TOTAL_FILES=$((TOTAL_FILES + 1))
    echo "Processing: $file"
    
    # Create backup
    cp "$file" "$file.backup"
    
    # Use a temp file to avoid sed path length issues
    temp_file=$(mktemp)
    
    # Apply fixes one by one
    cat "$file" > "$temp_file"
    
    # Fix: Remove quotes around variables like "${BASE_DOMAIN}" -> ${BASE_DOMAIN}
    sed 's/"\(\${[^}]*}\)"/\1/g' "$temp_file" > "$temp_file.1"
    
    # Fix: host: "service.${VAR}" -> host: service.${VAR}
    sed 's/host: "\([^"]*\)\.\(\${[^}]*}\)"/host: \1.\2/g' "$temp_file.1" > "$temp_file.2"
    
    # Fix: host: service.${VAR}" -> host: service.${VAR}
    sed 's/host: \([^"[:space:]]*\)\.\(\${[^}]*}\)"/host: \1.\2/g' "$temp_file.2" > "$temp_file.3"
    
    # Fix: host: service.${VAR}"" -> host: service.${VAR}
    sed 's/host: \([^"[:space:]]*\)\.\(\${[^}]*}\)""/host: \1.\2/g' "$temp_file.3" > "$temp_file.4"
    
    # Fix array format: - host: patterns
    sed 's/- host: "\([^"]*\)\.\(\${[^}]*}\)"/- host: \1.\2/g' "$temp_file.4" > "$temp_file.5"
    sed 's/- host: \([^"[:space:]]*\)\.\(\${[^}]*}\)"/- host: \1.\2/g' "$temp_file.5" > "$temp_file.6"
    
    # Fix any remaining quoted variables in other contexts
    sed 's/: "\(\${[^}]*}\)"/: \1/g' "$temp_file.6" > "$temp_file.final"
    
    # Replace original file
    mv "$temp_file.final" "$file"
    
    # Clean up temp files
    rm -f "$temp_file" "$temp_file.1" "$temp_file.2" "$temp_file.3" "$temp_file.4" "$temp_file.5" "$temp_file.6"
    
    # Check if changes were made
    if ! cmp -s "$file" "$file.backup"; then
        MODIFIED_FILES=$((MODIFIED_FILES + 1))
        echo "  ✓ Fixed quote positioning"
    else
        echo "  - No changes needed"
        rm -f "$file.backup"
    fi
done
echo ""
echo "Summary:"
echo "- Files processed: $TOTAL_FILES"
echo "- Files modified: $MODIFIED_FILES"
