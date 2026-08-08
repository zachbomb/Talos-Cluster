# Runbook: raise Talos VM (105) from 8 → 10 vCPU

**Type:** Proxmox hypervisor change. **NOT repo-controlled** — manual, out-of-band.
Nothing here is committed or reconciled; Flux has no visibility into it.

**Status:** ready to execute. **Gated on the Pibbs-Horde scrub finishing.**

---

## Why

The Kubernetes node is not short of *physical* CPU. It is short of *vCPU*: it sits at
an 8-vCPU ceiling while ~2 host threads go unused, because TrueNAS is allocated 6 and
uses barely 1.

Measured 2026-08-08, two independent instruments agreeing:

```
Proxmox, 5 samples 20s apart (VM figures stable across all five):
  vm105 Talos      8.57 – 8.65 threads    allocated 8   <- PEGGED at its ceiling
  vm100 TrueNAS    1.03 – 1.23 threads    allocated 6   <- using ~19%
  Roon + homebridge + PBS      ~0.24 threads

Prometheus, independent, 15-min average:
  k8s node using 7.30 of 8 vCPU = 91% sustained

Host: Xeon W-1250, 6C/12T = 12 threads. Real demand ~10.0 of 12.
```

Downstream symptoms, all traced to this one cause:

- VolSync movers unschedulable (node at 95% CPU *requests*), then SIGKILLed when they start
- metrics-server crash-loop — kubelet cannot serve `/metrics/resource` inside 10s
- Tunarr transcode measured at 0.83x realtime (and `-readrate 1` means it can never catch up)
- restart storm: kube-controller-manager 18, cilium-operator 17, metrics-server 16,
  metallb-controller 14 — the BestEffort probe-starvation class

## Why this is safe

- ~2 threads are genuinely idle. This claims real capacity, not paper capacity.
- **TrueNAS is NOT touched.** It keeps all 6 vCPU for scrub/resilver spikes. It merely
  stops sitting on idle threads nothing else may use.
- Oversubscription goes 17 -> 19 vCPU on 12 threads. That is fine: actual demand is ~10.
  Oversubscription only bites when everyone demands simultaneously.
- `cpuunits` already favour Talos: vm105=4096, vm100=3072, everything else=256. Under
  genuine contention Talos already wins. Do not change these.

## Cost

**A full outage of the single-node cluster** — Plex, Tunarr, media stack, everything —
for roughly 5–10 minutes. Do not run this while anyone is watching live TV.

CPU hotplug exists in Proxmox but Talos guest support is unverified. Assume a shutdown.

---

## Preconditions

- [ ] `Pibbs-Horde` scrub is **FINISHED** (it was 86.59% with ~7.1h left and `errors=1`
      at 2026-08-08 ~02:55Z). Rebooting mid-scrub risks the JBOD link — see the
      USB/UAS link-collapse history.
- [ ] The `errors=1` from that scrub has been read and understood first.
- [ ] Nobody is streaming.
- [ ] Note the current backup gap so you can confirm recovery afterwards.

## Steps

1. Confirm the scrub is done:
   ```bash
   curl -sk -u 'media:<pw>' https://192.168.10.122:444/api/v2.0/pool | jq '.[].scan.state'
   ```
   Expect `FINISHED` for Pibbs-Horde. **Stop if it says SCANNING.**

2. Graceful guest shutdown (Talos flushes etcd cleanly):
   ```bash
   qm shutdown 105 --timeout 300
   qm status 105          # expect: status: stopped
   ```
   If it does not stop within the timeout, investigate — do **not** `qm stop` a running
   etcd node unless you have to.

3. Change the core count:
   ```bash
   qm set 105 --cores 10
   qm config 105 | grep -E '^(cores|sockets|cpuunits|numa)'
   ```
   Expect `cores: 10`, `sockets: 1`, `cpuunits: 4096`. Leave sockets and cpuunits alone.

4. Start:
   ```bash
   qm start 105
   ```

5. Verify at the hypervisor:
   ```bash
   qm config 105 | grep cores        # cores: 10
   ```

6. Verify in Kubernetes (allow a few minutes for the node to register):
   ```bash
   kubectl get node k8s-control-1 -o jsonpath='{.status.capacity.cpu}'   # expect 10
   kubectl describe node k8s-control-1 | grep -A4 'Allocated resources'
   ```
   CPU requests should drop from ~95% to roughly **76%** (7566m of 9950m).

## Post-change verification

- [ ] Node capacity reads 10.
- [ ] VolSync movers begin scheduling — the ~24-deep queue should start draining
      serially. They are priority -100 by design; expect one or two at a time.
      ```bash
      kubectl get pods -A | grep volsync-src | awk '{print $4}' | sort | uniq -c
      ```
- [ ] Backups actually complete (not just start):
      ```bash
      kubectl get replicationsource -A -o wide | grep -E 'tunarr|calibre|cwa|nzbget|overseerr'
      ```
      `lastSyncTime` must advance past 2026-08-06T05:09:52Z.
- [ ] metrics-server stops crash-looping and `kubectl top nodes` works again. If it does
      **not** recover, the kubelet timeout is a separate defect rather than a symptom —
      that is useful information, not a failure of this change.
- [ ] Restore SonarQube, which was scaled to 0 to free 200m during the incident:
      ```bash
      kubectl scale statefulset -n sonarqube sonarqube-sonarqube --replicas=1
      ```
      Do this **after** the backup queue has drained, not before.
- [ ] Re-measure the Tunarr transcode rate. If it was starved rather than
      mis-configured, it should move back toward 1.0x. It cannot exceed 1.0x —
      `-readrate 1` caps it — so this only removes the deficit, it does not rebuild
      the cushion. That is a separate fix in `ffmpeg-wrap.sh`.

## Rollback

Fully reversible, same outage cost:

```bash
qm shutdown 105 --timeout 300
qm set 105 --cores 8
qm start 105
```

## What this does NOT fix

- **The 0.83x transcode deficit may only partly close.** `-threads 1` is forced by
  Tunarr whenever hardware decode is active ("Forcing 1 ffmpeg decoding thread due to
  use of hardware accelerated decoding"), so a single decode thread on a shared VAAPI
  device remains the constraint. Offloading to the passed-through RTX A4000 (NVENC)
  is the separate lever.
- **`-readrate 1` still forbids catch-up.** More CPU stops the deficit accruing; it
  does not let the pipeline rebuild a cushion it has already lost.
- **The host still has only 12 threads.** This claims the last ~2 of them. There is no
  third bite at this apple without a CPU swap (W-1250 is LGA1200; a W-1290P is 10C/20T
  — verify QNAP board/BIOS support before buying anything).
