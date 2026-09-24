#!/usr/bin/env python3
"""Keep Plex's DVR channel map in step with Tunarr's lineup.

WHY THIS EXISTS. Plex never maps a new HDHomeRun channel on its own. Every Tunarr
channel we add stays invisible in Plex Live TV until someone maps it. That has
bitten three times: 2026-08-28 (11 channels), 2026-09-17 (ch35), 2026-09-24 (ch35
still, plus ch37). The only fix used before was the Plex UI's re-add-device flow,
which can reset every existing mapping, so it kept getting skipped.

WHAT IT DOES. It makes the same call Plex Web makes when you save the channel list:

    PUT /media/grabbers/devices/<device>/channelmap
        channelMapping[<id>]=<lineupIdentifier>
        channelMappingByKey[<id>]=<epg channel key>
        channelsEnabled=<every id>

That PUT REPLACES the whole map, so the body always carries every existing mapping
unchanged, and adds only:
  * channels Tunarr advertises that Plex has not mapped, and
  * mappings whose guide key no longer matches the guide (a rebuilt channel can get
    a new XMLTV id).
It never removes a mapping. It refuses to write if the result would have fewer
mappings than before. Afterwards it re-reads the map, verifies it, and reloads
the guide.

Env: PLEX_URL, PLEX_API (never on argv), TUNARR_URL. Use --dry-run to only report.
Exit codes: 0 = in sync or fixed; 1 = verification failed; 2 = could not read state.
NB: this file is mounted through a Flux-substituted ConfigMap. Do not add a dollar
sign anywhere in it: Flux would substitute or eat it.
"""
import json, os, re, sys, urllib.parse, urllib.request

PLEX = os.environ.get("PLEX_URL", "http://192.168.10.203:32400").rstrip("/")
TOKEN = os.environ.get("PLEX_API", "")
TUNARR = os.environ.get("TUNARR_URL", "http://192.168.10.205:8000").rstrip("/")
DRY = "--dry-run" in sys.argv
TIMEOUT = 120


def log(msg):
    print("[plex-dvr-sync] " + msg, flush=True)


def fetch(url, method="GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read().decode("utf-8", "replace")


def plex(path, method="GET", params=None):
    q = list(params or []) + [("X-Plex-Token", TOKEN)]
    sep = "&" if "?" in path else "?"
    return fetch(PLEX + path + sep + urllib.parse.urlencode(q), method)


def attrs(tag):
    return dict(re.findall(r'(\w+)="([^"]*)"', tag))


def tags(xml, name):
    return [attrs(t) for t in re.findall(r"<" + name + r"\b[^>]*>", xml)]


def tunarr_dvr(xml):
    """Return (dvr, device, mappings) for the DVR whose device is Tunarr."""
    host = urllib.parse.urlparse(TUNARR).hostname or ""
    for block in re.findall(r"<Dvr\b.*?</Dvr>", xml, re.S):
        dvr = attrs(re.search(r"<Dvr\b[^>]*>", block).group(0))
        for dev_block in re.findall(r"<Device\b.*?</Device>", block, re.S):
            dev = attrs(re.search(r"<Device\b[^>]*>", dev_block).group(0))
            if "Tunarr" in dev.get("make", "") + dev.get("model", "") or host in dev.get("uri", ""):
                maps = {m["deviceIdentifier"]: m for m in tags(dev_block, "ChannelMapping")}
                return dvr, dev, maps
    return None, None, None


def main():
    if not TOKEN:
        log("PLEX_API is empty; nothing to do")
        return 2
    try:
        _, lineup_raw = fetch(TUNARR + "/lineup.json")
        lineup = {str(c["GuideNumber"]): c.get("GuideName", "") for c in json.loads(lineup_raw)}
        _, dvrs_xml = plex("/livetv/dvrs")
    except Exception as e:
        log("cannot read Tunarr lineup or Plex DVRs: " + repr(e))
        return 2
    dvr, dev, before = tunarr_dvr(dvrs_xml)
    if dvr is None:
        log("no Plex DVR with a Tunarr device found; refusing to guess")
        return 2
    log("DVR " + dvr["key"] + " device " + dev["key"] + " (" + dev.get("uri", "") + ") status=" + dev.get("status", "?")
        + " | tunarr channels " + str(len(lineup)) + ", plex mappings " + str(len(before)))

    lineup_uri = dvr.get("lineup", "")
    try:
        _, dev_xml = plex("/media/grabbers/devices/" + dev["key"] + "/channels")
        _, epg_xml = plex("/livetv/epg/channels", params=[("lineup", lineup_uri)])
    except Exception as e:
        log("cannot read device/guide channels: " + repr(e))
        return 2
    device_ids = [d["identifier"] for d in tags(dev_xml, "DeviceChannel")]
    epg = {c["identifier"]: c for c in tags(epg_xml, "Channel")}
    if not device_ids or not epg:
        log("empty device or guide channel list (device=" + str(len(device_ids)) + ", guide=" + str(len(epg)) + "); refusing to write")
        return 2

    plan, adds, fixes = {}, [], []
    for d in device_ids:
        cur = before.get(d)
        g = epg.get(d)
        if cur and (g is None or cur.get("channelKey") == g.get("key")):
            plan[d] = (cur["lineupIdentifier"], cur["channelKey"])       # unchanged
        elif cur and g:
            plan[d] = (g["identifier"], g["key"]); fixes.append(d + ": " + cur.get("channelKey", "") + " -> " + g["key"])
        elif g:
            plan[d] = (g["identifier"], g["key"]); adds.append(d + " " + lineup.get(d, g.get("title", "")))
    for d, m in before.items():                                          # never drop a mapping
        plan.setdefault(d, (m["lineupIdentifier"], m["channelKey"]))

    not_on_device = sorted(set(lineup) - set(device_ids), key=lambda x: int(x) if x.isdigit() else 0)
    no_guide = [d for d in device_ids if d not in before and d not in epg]
    orphaned = sorted(set(before) - set(lineup))
    disabled = [d for d, m in before.items() if m.get("enabled") != "1"]
    if not_on_device:
        log("WARN Tunarr channels Plex's device list does not have yet (it refreshes lineup.json on its own): " + ", ".join(not_on_device))
    if no_guide:
        log("WARN channels with no guide entry, not mappable yet: " + ", ".join(no_guide))
    if orphaned:
        log("NOTE mappings for channels Tunarr no longer advertises (left alone): " + ", ".join(orphaned))

    if not adds and not fixes and not disabled:
        log("in sync: " + str(len(before)) + " mappings, all enabled")
        return 0
    log("plan: add [" + "; ".join(adds) + "] fix [" + "; ".join(fixes) + "] re-enable [" + ", ".join(disabled) + "]")
    if len(plan) < len(before):
        log("ABORT: plan has fewer mappings than Plex does now")
        return 1
    if DRY:
        log("dry run: nothing written")
        return 0

    q = []
    for d, (li, key) in plan.items():
        q += [("channelMapping[" + d + "]", li), ("channelMappingByKey[" + d + "]", key)]
    q.append(("channelsEnabled", ",".join(plan)))
    status, _ = plex("/media/grabbers/devices/" + dev["key"] + "/channelmap", "PUT", q)
    log("PUT channelmap -> " + str(status))

    _, after_xml = plex("/livetv/dvrs")
    _, _, after = tunarr_dvr(after_xml)
    bad = [d for d, (li, key) in plan.items()
           if d not in after or after[d].get("channelKey") != key or after[d].get("enabled") != "1"]
    lost = [d for d in before if d not in after]
    if bad or lost:
        log("VERIFY FAILED: wrong/disabled " + ", ".join(bad) + " | lost " + ", ".join(lost))
        return 1
    status, _ = plex("/livetv/dvrs/" + dvr["key"] + "/reloadGuide", "POST")
    log("verified " + str(len(after)) + " mappings; reloadGuide -> " + str(status))
    return 0


if __name__ == "__main__":
    sys.exit(main())
