#!/bin/bash

# Script to restore critical prometheus configurations while keeping improvements

PROMETHEUS_FILE="clusters/main/kubernetes/system/kube-prometheus-stack/app/helm-release.yaml"
OLD_COMMIT="18dd30c"

# Backup current file
cp "$PROMETHEUS_FILE" "${PROMETHEUS_FILE}.backup"

# Extract specific sections from old commit
git show ${OLD_COMMIT}:${PROMETHEUS_FILE} > /tmp/old-prometheus.yaml

# Use yq to merge specific sections
echo "Restoring kubeControllerManager section..."
yq eval '.spec.values.kubeControllerManager' /tmp/old-prometheus.yaml > /tmp/controller-manager.yaml

echo "Restoring kubeScheduler section..."
yq eval '.spec.values.kubeScheduler' /tmp/old-prometheus.yaml > /tmp/scheduler.yaml

echo "Restoring storageSpec section..."
yq eval '.spec.values.prometheus.prometheusSpec.storageSpec' /tmp/old-prometheus.yaml > /tmp/storage.yaml

echo "Restoring resource limits..."
yq eval '.spec.values.prometheus.prometheusSpec.resources' /tmp/old-prometheus.yaml > /tmp/resources.yaml

echo "Restoring VPA settings..."
yq eval '.spec.values.autoscaling' /tmp/old-prometheus.yaml > /tmp/vpa.yaml

echo "Restoring metricLabelsAllowlist..."
yq eval '.spec.values."kube-state-metrics".metricLabelsAllowlist' /tmp/old-prometheus.yaml > /tmp/metrics.yaml

# Merge back into current file
yq eval-all '
  select(fileIndex == 0) as $current |
  select(fileIndex == 1) as $controller |
  select(fileIndex == 2) as $scheduler |
  select(fileIndex == 3) as $storage |
  select(fileIndex == 4) as $resources |
  select(fileIndex == 5) as $vpa |
  select(fileIndex == 6) as $metrics |
  $current |
  .spec.values.kubeControllerManager = $controller |
  .spec.values.kubeScheduler = $scheduler |
  .spec.values.prometheus.prometheusSpec.storageSpec = $storage |
  .spec.values.prometheus.prometheusSpec.resources = $resources |
  .spec.values.autoscaling = $vpa |
  .spec.values."kube-state-metrics".metricLabelsAllowlist = $metrics
' "$PROMETHEUS_FILE" /tmp/controller-manager.yaml /tmp/scheduler.yaml /tmp/storage.yaml /tmp/resources.yaml /tmp/vpa.yaml /tmp/metrics.yaml > /tmp/merged-prometheus.yaml

# Replace current file with merged version
mv /tmp/merged-prometheus.yaml "$PROMETHEUS_FILE"

# Clean up temp files
rm -f /tmp/old-prometheus.yaml /tmp/controller-manager.yaml /tmp/scheduler.yaml /tmp/storage.yaml /tmp/resources.yaml /tmp/vpa.yaml /tmp/metrics.yaml

echo "Prometheus configuration restored. Review changes with:"
echo "git diff ${PROMETHEUS_FILE}"
echo ""
echo "If satisfied, commit with:"
echo "git add ${PROMETHEUS_FILE} && git commit -m 'Restore critical prometheus monitoring configurations'"
