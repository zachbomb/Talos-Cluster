#!/bin/bash

echo "=== Fixing Flannel Configuration ==="
echo ""

echo "1. Check Flannel pod status..."
kubectl get pods -n kube-flannel -o wide
echo ""

echo "2. Check Flannel logs for errors..."
kubectl logs -n kube-flannel -l app=flannel --tail=20
echo ""

echo "3. Check if Flannel config is properly applied..."
kubectl get configmap -n kube-flannel kube-flannel-cfg -o yaml
echo ""

echo "4. Force restart Flannel pods to reinitialize..."
kubectl delete pods -n kube-flannel -l app=flannel
echo "Waiting for Flannel pods to restart..."
sleep 30
kubectl wait --for=condition=Ready pod -l app=flannel -n kube-flannel --timeout=120s
echo ""

echo "5. Check if subnet.env file is created..."
# Create a debug pod to check the flannel directory
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: flannel-debug
  namespace: kube-system
spec:
  hostNetwork: true
  containers:
  - name: debug
    image: alpine:latest
    command:
    - /bin/sh
    - -c
    - |
      echo "Checking Flannel directories..."
      ls -la /host/run/flannel/ || echo "/run/flannel directory not found"
      ls -la /host/var/lib/flannel/ || echo "/var/lib/flannel directory not found"
      echo "Checking CNI configuration..."
      ls -la /host/etc/cni/net.d/
      cat /host/etc/cni/net.d/10-flannel.conflist || echo "Flannel config not found"
      echo "Waiting..."
      sleep 60
    securityContext:
      privileged: true
    volumeMounts:
    - name: run
      mountPath: /host/run
    - name: var-lib
      mountPath: /host/var/lib
    - name: cni-netd
      mountPath: /host/etc/cni/net.d
  volumes:
  - name: run
    hostPath:
      path: /run
  - name: var-lib
    hostPath:
      path: /var/lib
  - name: cni-netd
    hostPath:
      path: /etc/cni/net.d
  restartPolicy: Never
EOF

echo ""
echo "6. Wait for debug info..."
kubectl wait --for=condition=Ready pod/flannel-debug -n kube-system --timeout=60s
sleep 10
kubectl logs flannel-debug -n kube-system
echo ""

echo "7. Clean up debug pod..."
kubectl delete pod flannel-debug -n kube-system

echo ""
echo "=== Flannel diagnosis complete ==="
