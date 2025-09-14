#!/bin/bash

# Corrected script to properly add loadBalancerIP to HelmRelease files
# Uses Python with PyYAML for proper YAML manipulation

set -e

get_ip_var() {
    case "$1" in
        *"nginx-internal"*) echo "\${NGINX_INTERNAL_IP}" ;;
        *"nginx-external"*) echo "\${NGINX_EXTERNAL_IP}" ;;
        *"kubernetes-dashboard"*) echo "\${DASHBOARD_IP}" ;;
        *"longhorn"*) echo "\${LONGHORN_IP}" ;;
        *"homepage"*) echo "\${HOMEPAGE_IP}" ;;
        *"blocky"*) echo "\${BLOCKY_IP}" ;;
        *"crowdsec"*) echo "\${CROWDSEC_IP}" ;;
        *"ollama"*) echo "\${OLLAMA_IP}" ;;
        *"traefik"*) echo "\${TRAEFIK_IP}" ;;
        *"plex"*) echo "\${PLEX_IP}" ;;
        *"emby"*) echo "\${EMBY_IP}" ;;
        *"tunarr"*) echo "\${TUNARR_IP}" ;;
        *"overseerr"*) echo "\${OVERSEERR_IP}" ;;
        *"radarr"*) echo "\${RADARR_IP}" ;;
        *"lidarr"*) echo "\${LIDARR_IP}" ;;
        *"mylar"*) echo "\${MYLAR_IP}" ;;
        *"readarr"*) echo "\${READARR_IP}" ;;
        *"bazarr"*) echo "\${BAZARR_IP}" ;;
        *"tdarr"*) echo "\${TDARR_IP}" ;;
        *"calibre-web"*) echo "\${CALIBRE_WEB_IP}" ;;
        *"calibre"*) echo "\${CALIBRE_IP}" ;;
        *"sonarr"*) echo "\${SONARR_IP}" ;;
        *"dizquetv"*) echo "\${DIZQUETV_IP}" ;;
        *"recyclarr"*) echo "\${RECYCLARR_IP}" ;;
        *"kapowarr"*) echo "\${KAPOWARR_IP}" ;;
        *"tautulli"*) echo "\${TAUTULLI_IP}" ;;
        *"sabnzbd"*) echo "\${SABNZBD_IP}" ;;
        *"nzbget"*) echo "\${NZBGET_IP}" ;;
        *"tandoor"*) echo "\${TANDOOR_IP}" ;;
        *"doplarr"*) echo "\${DOPLARR_IP}" ;;
        *"notifiarr"*) echo "\${NOTIFIARR_IP}" ;;
        *"tinymediamanager"*) echo "\${TINYMEDIAMANAGER_IP}" ;;
        *) echo "" ;;
    esac
}

process_yaml_file() {
    local file="$1"
    local ip_var="$2"
    
    python3 -c "
import yaml
import sys
import os
from collections import OrderedDict

# Custom YAML loader/dumper to preserve order and formatting
class OrderedLoader(yaml.SafeLoader):
    pass

class OrderedDumper(yaml.SafeDumper):
    pass

def dict_representer(dumper, data):
    return dumper.represent_mapping(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        data.items())

def dict_constructor(loader, node):
    return OrderedDict(loader.construct_pairs(node))

OrderedDumper.add_representer(OrderedDict, dict_representer)
OrderedLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    dict_constructor)

try:
    with open('$file', 'r') as f:
        content = f.read()
        
    # Parse YAML while preserving structure
    data = yaml.load(content, Loader=OrderedLoader)
    
    if not data or 'spec' not in data or 'values' not in data['spec']:
        print('No spec.values section found')
        sys.exit(0)
    
    values = data['spec']['values']
    modified = False
    
    def find_and_modify_services(obj, path=''):
        nonlocal modified
        if isinstance(obj, dict):
            # Check if this is a service configuration
            if obj.get('type') == 'LoadBalancer':
                # Add loadBalancerIP if not present
                if 'loadBalancerIP' not in obj:
                    obj['loadBalancerIP'] = '$ip_var'
                    modified = True
                    print(f'  Added loadBalancerIP to: {path}')
                
                # Ensure annotations exist
                if 'annotations' not in obj:
                    obj['annotations'] = OrderedDict()
                
                # Add MetalLB annotation if not present
                if 'metallb.universe.tf/loadBalancerIPs' not in obj['annotations']:
                    obj['annotations']['metallb.universe.tf/loadBalancerIPs'] = '$ip_var'
                    modified = True
                    print(f'  Added MetalLB annotation to: {path}')
                
                return
            
            # Recursively search through the dictionary
            for key, value in obj.items():
                new_path = f'{path}.{key}' if path else key
                find_and_modify_services(value, new_path)
                
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                new_path = f'{path}[{i}]'
                find_and_modify_services(item, new_path)
    
    # Search through all values
    find_and_modify_services(values)
    
    if modified:
        # Write back the modified YAML
        with open('$file', 'w') as f:
            yaml.dump(data, f, Dumper=OrderedDumper, default_flow_style=False, 
                     indent=2, allow_unicode=True, sort_keys=False)
        print('  File modified successfully')
    else:
        print('  No LoadBalancer services found or already configured')
    
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)
"
}

SEARCH_DIR="${1:-.}"
echo "Processing HelmRelease files in: $SEARCH_DIR"

TOTAL_FILES=0
MODIFIED_FILES=0

# Use a different approach to avoid the while read issue
mapfile -t helm_files < <(find "$SEARCH_DIR" -name "*.yaml" -o -name "*.yml")

for file in "${helm_files[@]}"; do
    if ! grep -q "kind: HelmRelease" "$file" 2>/dev/null; then
        continue
    fi
    
    TOTAL_FILES=$((TOTAL_FILES + 1))
    echo "Processing: $file"
    
    # Get service name from filename
    basename_file=$(basename "$file" .yaml)
    basename_file=$(basename "$basename_file" .yml)
    
    # Get IP variable
    ip_var=$(get_ip_var "$basename_file")
    
    if [[ -z "$ip_var" ]]; then
        echo "  No IP mapping for: $service_name (extracted from path/content)"
        continue
    fi
    
    echo "  Service: $service_name -> IP: $ip_var"
    
    # Create backup
    cp "$file" "$file.backup"
    
    # Process the YAML file
    if process_yaml_file "$file" "$ip_var"; then
        # Check if changes were actually made
        if ! cmp -s "$file" "$file.backup"; then
            MODIFIED_FILES=$((MODIFIED_FILES + 1))
            echo "  ✓ Modified successfully"
        else
            echo "  - No changes needed"
            rm -f "$file.backup"
        fi
    else
        echo "  ✗ Failed to process"
        # Restore backup on failure
        mv "$file.backup" "$file"
    fi
done < "$temp_file"

# Clean up temporary file
rm -f "$temp_file"

echo ""
echo "Summary:"
echo "- Files processed: $TOTAL_FILES"
echo "- Files modified: $MODIFIED_FILES"
echo ""
echo "Review .backup files before committing changes."
echo "To clean up: find $SEARCH_DIR -name '*.backup' -delete"
