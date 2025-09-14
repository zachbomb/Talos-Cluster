#!/bin/bash

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

SEARCH_DIR="${1:-.}"
echo "Processing HelmRelease files in: $SEARCH_DIR"

# Process files one by one
for file in $(find "$SEARCH_DIR" -name "*.yaml" -o -name "*.yml"); do
    # Skip if not a HelmRelease
    if ! grep -q "kind: HelmRelease" "$file" 2>/dev/null; then
        continue
    fi
    
    echo "Processing: $file"
    
    # Extract service name from path
    service_name=""
    if [[ "$file" == */app/helm-release.yaml ]]; then
        path_without_end="${file%/app/helm-release.yaml}"
        service_name="${path_without_end##*/}"
    fi
    
    echo "  Extracted service: $service_name"
    
    # Get IP variable
    ip_var=$(get_ip_var "$service_name")
    
    if [[ -z "$ip_var" ]]; then
        echo "  No IP mapping found"
        continue
    fi
    
    echo "  IP variable: $ip_var"
    
    # Check if already has loadBalancerIP
    if grep -q "loadBalancerIP:" "$file"; then
        echo "  Already configured"
        continue
    fi
    
    # Check if file has LoadBalancer service
    if ! grep -q "type: LoadBalancer" "$file"; then
        echo "  No LoadBalancer service found"
        continue
    fi
    
    echo "  Adding loadBalancerIP configuration..."
    
    # Create backup
    cp "$file" "$file.backup"
    
    # Use Python to add the configuration
    python3 -c "
import yaml
try:
    with open('$file', 'r') as f:
        data = yaml.safe_load(f)
    
    def add_lb_config(obj):
        if isinstance(obj, dict):
            if obj.get('type') == 'LoadBalancer':
                obj['loadBalancerIP'] = '$ip_var'
                if 'annotations' not in obj:
                    obj['annotations'] = {}
                obj['annotations']['metallb.universe.tf/loadBalancerIPs'] = '$ip_var'
                return True
            for value in obj.values():
                if add_lb_config(value):
                    return True
        elif isinstance(obj, list):
            for item in obj:
                if add_lb_config(item):
                    return True
        return False
    
    if add_lb_config(data):
        with open('$file', 'w') as f:
            yaml.dump(data, f, default_flow_style=False, indent=2)
        print('  SUCCESS: Modified file')
    else:
        print('  No LoadBalancer service found to modify')
        
except Exception as e:
    print(f'  ERROR: {e}')
"
    
done

echo "Done! Check .backup files for changes."
