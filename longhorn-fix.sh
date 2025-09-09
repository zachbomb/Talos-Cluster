# List of Longhorn resource types
resources=(
  engineimages.longhorn.io
  engines.longhorn.io
  nodes.longhorn.io
  volumeattachments.longhorn.io
  volumes.longhorn.io
)

# Loop through each type and remove finalizers
for r in "${resources[@]}"; do
  echo "Processing $r..."

  # Get all resource names
  for name in $(kubectl get "$r" -n longhorn-system -o jsonpath='{.items[*].metadata.name}'); do
    echo "  - Patching $name..."
    kubectl patch "$r" "$name" -n longhorn-system -p '{"metadata":{"finalizers":[]}}' --type=merge
  done
done

