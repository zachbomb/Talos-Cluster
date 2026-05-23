---
paths:
- clusters/main/kubernetes/kube-system/**
- clusters/main/kubernetes/system/metallb/**
- clusters/main/kubernetes/system/longhorn/**
- clusters/main/kubernetes/system/cert-manager/**
- clusters/main/kubernetes/core/cilium/**
- clusters/main/kubernetes/core/blocky/**
---

# Cilium Gotchas
- **ICMP to LoadBalancer IPs**: Cilium BPF with `kubeProxyReplacement: true` does NOT handle ICMP. LoadBalancer IPs won't respond to `ping`. Always test with `curl`.
- **`externalTrafficPolicy: Local`**: Breaks same-subnet LB traffic on single-node clusters. Use `Cluster`.
- **NetworkPolicy ports**: Must use **container ports** (e.g. 8000/8443/8080 for Traefik), not service ports (80/443/9000).

# MetalLB IP Conflicts
When many apps install simultaneously, MetalLB auto-assigns IPs to services missing the `metallb.io/loadBalancerIPs` annotation, stealing reserved IPs. Fix: delete the conflicting service to free the IP, then let it re-create with the annotation.

# Longhorn/cert-manager CRDs
Both have CRDs in `templates/crds.yaml` (not `crds/` directory). Flux `crds: CreateReplace` only works for CRDs in `crds/`. Missing CRDs must be applied manually via `helm template`.
- cert-manager: ensure `installCRDs: true` in values.
- Renovate is **disabled** for the Longhorn chart (Kyverno image digest mutation caused 1.11 upgrade loop).
- Kyverno excludes `longhorn-system` and adds `cnpg.io/podRole=instance` label exclusion to prevent CNPG instance pod image mutation.
