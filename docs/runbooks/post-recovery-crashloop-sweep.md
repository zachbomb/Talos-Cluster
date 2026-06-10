After a cluster recovery event (Talos boot wedge, control-plane restart, etcd recovery), some pods stay stuck in CrashLoopBackOff indefinitely even though the underlying issue has cleared. The container's own backoff timer becomes the only retry mechanism, and exponential backoff means waits of 5+ minutes between attempts.

Hit during the 2026-06-09 PR 5 incident: `networking/nebula-sync` showed `connect: operation not permitted` to `pihole-k8s.networking.svc:9089` for 5h+ with 14 restarts. Initial reading suggested a Cilium NetworkPolicy denial. Actual cause: nebula-sync started during the post-reboot window when pihole-k8s wasn't ready, hit FATAL on first sync attempt, exited non-zero, and stayed in CrashLoopBackOff. After the cluster fully recovered, `kubectl delete pod -n networking -l app.kubernetes.io/name=nebula-sync` triggered a fresh start — sync completed in <1 second.

**Why:** Why save this as feedback — some containers (Go binaries, single-shot syncers, tight startup-probe services) treat their first failure as fatal rather than implementing internal retry. Kubernetes' container backoff is the only retry trigger, and exponential backoff caps at 5 minutes between attempts. So a 30-second transient at startup can turn into hours of CrashLoopBackOff even after the underlying issue resolves. The EPERM error in particular is misleading — Cilium can briefly return `operation not permitted` during destination endpoint state transitions (pod restart, identity churn), making it look like a NetworkPolicy denial when it's actually transient.

**How to apply:** After any cluster-level recovery event, run this sweep before diagnosing individual pod failures:

```bash
# Find CrashLoop pods that aren't restart-flapping (low restart count = stuck)
kubectl get pods -A --no-headers | awk '$4=="CrashLoopBackOff" && $5 < 5'

# Delete to force fresh start
kubectl get pods -A --no-headers | awk '$4=="CrashLoopBackOff" && $5 < 5 {print "kubectl delete pod -n "$1" "$2}'
```

If a pod comes back healthy after deletion, the original was transient. If it crashes again, dig in. **Do this BEFORE spending time on Cilium policy verdicts or NetworkPolicy analysis** — those are real but rare causes; transient-during-recovery is much more common.

Related: `genconfig-decrypts-in-place`, `traefik-stale-router-map-after-cascade` (Traefik has a similar pattern — needs rolling restart after rapid Ingress churn).
