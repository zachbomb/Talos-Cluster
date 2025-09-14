#!/bin/bash

# Script to add quotes around environment variable substitutions in HelmRelease YAML files
# This fixes issues where ${VAR} should be "${VAR}" for proper string interpolation

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Default directory to search (current directory)
SEARCH_DIR="${1:-.}"

print_status "Searching for HelmRelease YAML files in: $SEARCH_DIR"

# Find all YAML files that contain HelmRelease
HELM_FILES=$(find "$SEARCH_DIR" -name "*.yaml" -o -name "*.yml" | xargs grep -l "kind: HelmRelease" 2>/dev/null || true)

if [[ -z "$HELM_FILES" ]]; then
    print_warning "No HelmRelease YAML files found in $SEARCH_DIR"
    exit 0
fi

# Counter for modifications
TOTAL_FILES=0
MODIFIED_FILES=0

# Process each file
while IFS= read -r file; do
    if [[ -z "$file" ]]; then
        continue
    fi
    
    TOTAL_FILES=$((TOTAL_FILES + 1))
    print_status "Processing: $file"
    
    # Create backup
    cp "$file" "$file.backup"
    
    # Use sed to find and replace unquoted environment variables
    # This regex looks for ${VAR} that are not already quoted
    # Pattern explanation:
    # - (?<!["']) - negative lookbehind for quotes
    # - \$\{[^}]+\} - matches ${VARIABLE_NAME}
    # - (?!["']) - negative lookahead for quotes
    
    # Since sed doesn't support lookbehind/lookahead, we'll use a different approach
    # We'll match patterns where ${VAR} is not preceded by a quote and not followed by a quote
    
    CHANGES_MADE=0
    
    # Method 1: Handle cases where ${VAR} is a standalone value (most common)
    if sed -i.tmp 's/: \${/: "\${/g; s/}\s*$/}"/g' "$file" 2>/dev/null; then
        if ! cmp -s "$file" "$file.tmp"; then
            CHANGES_MADE=1
        fi
        rm -f "$file.tmp"
    fi
    
    # Method 2: Handle cases in arrays/lists
    if sed -i.tmp 's/- \${/- "\${/g' "$file" 2>/dev/null; then
        if ! cmp -s "$file" "$file.tmp"; then
            CHANGES_MADE=1
        fi
        rm -f "$file.tmp"
    fi
    
    # Method 3: More comprehensive pattern matching
    # This catches edge cases where variables might be embedded differently
    perl -i -pe '
        # Skip lines that already have quoted variables
        next if /["'"'"']\$\{[^}]+\}["'"'"']/;
        
        # Quote unquoted variables that are standalone values
        s/^(\s*\w+:\s*)\$\{([^}]+)\}(\s*)$/$1"\$\{$2\}"$3/g;
        
        # Quote unquoted variables in arrays
        s/^(\s*-\s*)\$\{([^}]+)\}(\s*)$/$1"\$\{$2\}"$3/g;
        
        # Handle variables in the middle of strings (partial matches)
        s/(\w+)(\$\{[^}]+\})(\w+)/"$1$2$3"/g;
    ' "$file" 2>/dev/null || print_warning "Perl processing failed for $file"
    
    # Check if any changes were made by comparing with backup
    if ! cmp -s "$file" "$file.backup"; then
        MODIFIED_FILES=$((MODIFIED_FILES + 1))
        print_status "Modified: $file"
        
        # Show what changed (first few differences)
        print_status "Changes made:"
        diff -u "$file.backup" "$file" | head -20 || true
        echo ""
    else
        print_status "No changes needed: $file"
        rm -f "$file.backup"  # Remove backup if no changes
    fi
    
done <<< "$HELM_FILES"

print_status "Summary:"
print_status "Total HelmRelease files processed: $TOTAL_FILES"
print_status "Files modified: $MODIFIED_FILES"

if [[ $MODIFIED_FILES -gt 0 ]]; then
    print_warning "Backup files created with .backup extension"
    print_warning "Please review changes before committing!"
    print_status "To remove backups after review: find $SEARCH_DIR -name '*.backup' -delete"
    
    echo ""
    print_status "To apply changes to your cluster:"
    print_status "flux reconcile kustomization --with-source"
fi
