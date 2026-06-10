## The problem

TrueCharts charts (immich, paperless-ngx, blocky, anything with a bundled `redis:` subchart = redis-2.3.4) default their valkey image to `docker.io/bitnamisecure/valkey:latest`. That's Bitnami's **paid Secure tier** — it returns HTTP 401 on pull. The pods only run because the image is cached on the node (`imagePullPolicy: IfNotPresent`). This survives normal reboots but **breaks on the next Talos OS upgrade** when all images re-pull. blocky-redis dying = cluster DNS degradation.

## What does NOT work

- **Raw image swap to `valkey/valkey`**: the official image is a plain valkey-server, missing the bitnami entrypoint that reads `VALKEY_PASSWORD`/`VALKEY_PORT` env vars and the `/health/ping_*_local.sh` probe scripts. App can't auth, probes fail.
- **`bitnamilegacy/valkey` (free archive)**: frozen at valkey 8.1.3, whose older valkey-cli doesn't honor the `VALKEYCLI_AUTH` env var the chart's health script uses → readiness probe gets `NOAUTH` → pod stuck 0/1. (The running bitnamisecure image is valkey 9.x which DOES honor it.) bitnamilegacy works for kubectl but NOT valkey-for-this-chart.

## What works: override command/args/probes

The TrueCharts redis subchart accepts container overrides under the parent's `redis:` key. Put this in the app's helm-release `values:`:

```yaml
redis:
  image:
    repository: docker.io/valkey/valkey
    tag: 8.1.8-alpine
    pullPolicy: IfNotPresent
  workload:
    main:
      podSpec:
        containers:
          main:
            command:
              - valkey-server
            args:
              - --requirepass
              - PLACEHOLDERPASSWORD      # the chart's hardcoded placeholder; app uses same
              - --port
              - "6379"
              - --dir
              - /tmp                     # writable emptyDir; image default /data is owned by UID 999, not the chart's 568
              - --save
              - ""                       # disable RDB snapshots
              - --appendonly
              - "no"                     # disable AOF — these are ephemeral caches, no PVC
            probes:
              liveness:
                type: exec
                command: [valkey-cli, -a, PLACEHOLDERPASSWORD, ping]
              readiness:
                type: exec
                command: [valkey-cli, -a, PLACEHOLDERPASSWORD, ping]
              startup:
                type: exec
                command: [valkey-cli, -a, PLACEHOLDERPASSWORD, ping]
```

Key facts that made it safe:
- These redis instances have **NO PVC** (`volumeClaimTemplates: []`) — they're ephemeral caches (immich=BullMQ queue, paperless=celery broker, blocky=DNS cache). Nothing to migrate; `--save "" --appendonly no` makes them pure in-memory.
- The password is the literal string `PLACEHOLDERPASSWORD` (chart default; the app's `REDIS_PASSWORD` env matches it). Hardcode it in the args.
- The chart's leftover `/health` configmap + emptyDir mounts are harmless — valkey just ignores them.

## The mandatory process (validated 2026-06-10)

1. **Render with `helm template` BEFORE applying** — confirm the override actually lands:
   ```bash
   helm template <app> oci://oci.trueforge.org/truecharts/<app> --version <ver> -f /tmp/override.yaml \
     | python3 -c "import sys,yaml; [print(d['spec']['template']['spec']['containers'][0].get('args')) for d in yaml.safe_load_all(sys.stdin) if isinstance(d,dict) and d.get('kind')=='StatefulSet' and 'redis' in d.get('metadata',{}).get('name','')]"
   ```
   Confirm image, command, args, and probe commands render correctly. This turns a fragile guess-and-iterate-on-live-DNS problem into a one-shot apply.

2. **Canary first** — migrate ONE low-risk app (immich), verify redis 1/1 Ready + `valkey-cli -a X ping` = PONG, before touching DNS-critical blocky.

3. **THE GOTCHA — bounce the client app pods after the swap.** The redis server comes up healthy, but the app's ioredis caches a connection to the OLD redis pod IP during the rollout window and gets stuck in backoff (`connect ETIMEDOUT`). The redis itself is fine (prove it with a debug pod hitting the service/ClusterIP/pod-IP). Fix:
   ```bash
   kubectl rollout restart deployment -n <ns> <app>
   ```
   Verify the ETIMEDOUT errors stop in the fresh pod's logs.

4. **blocky LAST** — it's DNS. After its redis swap + blocky restart, verify:
   ```bash
   nslookup grafana.sf.wethecommon.com 192.168.10.195   # internal split-horizon → .196
   nslookup google.com 192.168.10.195                    # external
   ```

## Verification it's complete

```bash
kubectl get pods -A -o json | python3 -c "
import json,sys
d=json.load(sys.stdin)
print([c['image'] for p in d['items'] for c in p['spec'].get('containers',[]) if 'bitnamisecure' in c.get('image','')])
"   # → []  (only bitnamilegacy/kubectl on the longhorn rotation CronJob is OK — free, intentional)
```

## Don't over-migrate

The bitnami exit was driven by a SPECIFIC problem (paid tier 401 on upgrade). The other ~150 deployments use healthy registries (ghcr.io, quay.io, registry.k8s.io, oci.trueforge.org) — no reason to touch them. Migrate problems, not images. This override technique is valkey-specific; it does not generalize to other charts without per-chart analysis.

Related: `kubectl-job-images` (the bitnamilegacy/kubectl decision for longhorn rotation), `post-recovery-crashloop-sweep`.
