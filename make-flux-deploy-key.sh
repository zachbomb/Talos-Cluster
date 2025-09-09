#!/bin/bash

# Script to recreate Flux deploykey.secret.yaml

DEPLOYKEY_FILE="clusters/main/kubernetes/flux-system/flux/deploykey.secret.yaml"
PRIVATE_KEY_PATH="$HOME/.ssh/flux-deploy-key"  # Adjust this path
PUBLIC_KEY_PATH="$HOME/.ssh/flux-deploy-key.pub"

# Check if deploy keys exist
if [[ ! -f "$PRIVATE_KEY_PATH" ]]; then
    echo "❌ Private key not found at $PRIVATE_KEY_PATH"
    echo "Generate new deploy key with:"
    echo "ssh-keygen -t ed25519 -C 'flux-deploy-key' -f $PRIVATE_KEY_PATH"
    echo "Then add the public key to GitHub: Settings > Deploy keys"
    exit 1
fi

echo "Creating deploykey.secret.yaml..."

# Encode the keys
PRIVATE_KEY_B64=$(base64 < "$PRIVATE_KEY_PATH" | tr -d '\n')
PUBLIC_KEY_B64=$(base64 < "$PUBLIC_KEY_PATH" | tr -d '\n')
KNOWN_HOSTS_B64=$(ssh-keyscan github.com 2>/dev/null | base64 | tr -d '\n')

# Create the secret file
cat > "$DEPLOYKEY_FILE" << EOF
apiVersion: v1
kind: Secret
metadata:
  name: flux-system
  namespace: flux-system
type: Opaque
data:
  identity: $PRIVATE_KEY_B64
  identity.pub: $PUBLIC_KEY_B64
  known_hosts: $KNOWN_HOSTS_B64
EOF

echo "✅ Created $DEPLOYKEY_FILE"
echo "Make sure the public key is added to GitHub as a deploy key"
