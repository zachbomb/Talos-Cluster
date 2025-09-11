#!/bin/bash

echo "=== Cleaning up Cilium CNI configuration and restarting networking ==="
echo ""

echo "1. Delete any remaining Cilium resources..."
kubectl delete -f https://raw.githubusercontent.com/cilium/cilium/v1.18.1/install/kubernetes/quick-install.yaml --ignore-not-found=true
kubectl delete namespace cilium-spire --ignore-not-found=true
kubectl delete crd --selector=io.cilium --ignore-not-found=true

echo ""
echo "2. Clean up CNI configuration on the node..."
# We need to remove Cilium CNI config files from the host
# This requires node access, which we'll do via a privileged pod

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: cni-cleanup
  namespace: kube-system
spec:
  hostNetwork: true
  hostPID: true
  containers:
  - name: cleanup
    image: alpine:latest
    command:
    - /bin/sh
    - -c
    - |
      echo "Cleaning up Cilium CNI configuration..."
      rm -f /host/etc/cni/net.d/*cilium*
      rm -f /host/etc/cni/net.d/05-cilium.conflist
      rm -f /host/opt/cni/bin/cilium-cni
      echo "Remaining CNI configs:"
      ls -la /host/etc/cni/net.d/
      echo "Cleanup complete, sleeping..."
      sleep 30
    securityContext:
      privileged: true
    volumeMounts:
    - name: cni-netd
      mountPath: /host/etc/cni/net.d
    - name: cni-bin
      mountPath: /host/opt/cni/bin
  volumes:
  - name: cni-netd
    hostPath:
      path: /etc/cni/net.d
  - name: cni-bin
    hostPath:
      path: /opt/cni/bin
  restartPolicy: Never
EOF

echo ""
echo "3. Wait for cleanup to complete..."
kubectl wait --for=condition=Ready pod/cni-cleanup -n kube-system --timeout=60s
sleep 10

echo ""
echo "4. Check cleanup results..."
kubectl logs cni-cleanup -n kube-system

echo ""
echo "5. Delete cleanup pod..."
kubectl delete pod cni-cleanup -n kube-system

echo ""
echo "6. Restart kubelet on the node to pick up new CNI config..."
echo "This requires access to the Talos node..."
echo "Run this command manually:"
echo "talosctl -n <NODE_IP> restart kubelet"

echo ""
echo "7. Restart Flannel to ensure clean state..."
kubectl delete -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml
sleep 10
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml

echo ""
echo "8. Wait for Flannel to be ready..."
kubectl wait --for=condition=Ready pod -l app=flannel -n kube-flannel --timeout=120s

echo ""
echo "=== Cleanup complete. Test DNS in a few minutes after kubelet restart ==="
