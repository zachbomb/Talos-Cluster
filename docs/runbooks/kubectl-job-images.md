# kubectl Image Strategy for in-cluster Jobs/CronJobs

When writing a Job or CronJob that runs `kubectl` against the local cluster, the image choice matters more than it seems. Wrong choice → ImagePullBackOff or RunContainerError. This runbook captures the trade-offs and the decision tree.

## Background

The original repo used `docker.io/bitnami/kubectl:1.36` everywhere. As of August 2025, Bitnami deprecated their free DockerHub images and moved them to `bitnamilegacy/*` (frozen archive) while `bitnami/*` now serves an HTML deprecation page that breaks pulls:

```
Failed to pull image "docker.io/bitnami/kubectl:1.36":
unexpected media type text/html for sha256:23f739be... : not found
```

The 2026-06-09 cluster reboot exposed this — the `instance-manager-rotation` CronJob had been ImagePullBackOff with 1200+ retries because nothing had triggered a pod restart since the deprecation.

## Decision tree

```
Does the script need a shell (set -o pipefail, bash arithmetic, date -d, awk)?
├── NO  → docker.io/rancher/kubectl:v1.36.1   (distroless, ENTRYPOINT=kubectl)
└── YES → does the script need a recent kubectl client (1.34+)?
          ├── NO  → docker.io/bitnamilegacy/kubectl:1.33.4  (frozen archive, Debian + bash)
          └── YES → write a Go binary with client-go, pin a digest, ship it via GHCR
```

## Option table

| Image | Maintained | Free | Has bash | Latest tag | Notes |
|---|---|---|---|---|---|
| `docker.io/rancher/kubectl:v1.36.1` | ✅ Active | ✅ | ❌ Distroless | Tracks K8s 1:1 | Only kubectl as ENTRYPOINT. Args become kubectl subcommands. |
| `docker.io/bitnamilegacy/kubectl:1.33.4` | ❌ Frozen archive | ✅ | ✅ /bin/bash 5.2.15 | 1.33.4 (Aug 2025) | Drop-in for the old bitnami/kubectl. UID 1001 non-root. **Use /bin/bash explicitly — /bin/sh is dash and rejects `set -o pipefail`.** |
| `docker.io/bitnami/kubectl:1.36` | ❌ Deprecated | ❌ | N/A | N/A | Serves HTML deprecation page. **Don't use.** |
| `docker.io/bitnamisecure/kubectl:1.36` | ✅ Active | ❌ Paid | ✅ | Tracks K8s 1:1 | Bitnami Premium subscription required. |
| Custom Go binary | ✅ You | ✅ | N/A (compiled) | You pick | Best for repeated patterns — pin a digest, build with goreleaser. |

## Gotchas observed in this repo

1. **bitnamilegacy/kubectl:1.33.4 has `dash` as /bin/sh**, not bash. The original bitnami image symlinked `/bin/sh -> bash`, so `set -o pipefail` worked. The legacy archive doesn't. **Always use `command: [/bin/bash, -c, ...]` explicitly with the legacy image, never `/bin/sh`.**

2. **rancher/kubectl is distroless**, not Alpine. The image's ENTRYPOINT is `kubectl` itself. `command: [/bin/sh, -c, ...]` fails with `exec: "/bin/sh": stat /bin/sh: no such file or directory`. Pass kubectl args directly: `command: [kubectl, get, pods, -n, default]`.

3. **kubectl client/server version skew** is supported within ±1 minor (officially) and works fine within ±3 for normal commands. bitnamilegacy 1.33 against cluster 1.36 is fine for `get/delete/jsonpath`. Avoid for new API resources introduced in 1.34+.

4. **client-go vs kubectl** — for repeated patterns, a 30-line Go program using client-go is more reliable than a shell script. No shell skew issues, deterministic behavior, faster startup. Worth the up-front time when the script will live > 1 year.

## Current usage in this repo

- `clusters/main/kubernetes/system/longhorn/app/instance-manager-rotation-cronjob.yaml` — uses `bitnamilegacy/kubectl:1.33.4` with `/bin/bash`. Set 2026-06-09 via PRs #4262 → #4263 → #4264.

If you add a new shell+kubectl CronJob, follow the bitnamilegacy + /bin/bash pattern from that file. If you add a pure-kubectl Job (no shell needed), prefer rancher/kubectl:v1.36.1.
