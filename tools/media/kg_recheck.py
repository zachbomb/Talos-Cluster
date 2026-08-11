#!/usr/bin/env python3
"""Re-check the ABSENT rows from the disc audit with a CORRECTED matcher.

THREE BUGS IN THE FIRST PASS, all producing false "not on KG":

1. ACCENT STRIPPING, not folding. `re.sub(r"[^a-z0-9]+","")` DELETES accented
   chars: "Celine" (KG) vs "Ce'line" -> "cline". Verified false negative on
   Celine And Julie Go Boating, which KG has 9 copies of. This is the same bug
   that silently skipped 31 French Chef files - fixed here with NFKD folding.

2. YEAR REQUIRED IN THE KG TITLE. The first pass demanded the year appear in the
   result title. The Leopard / Mirror / Killer of Sheep / Black Girl all returned
   results with NO year match, so a canonical arthouse title read as absent.
   Year is now a CONFIDENCE signal, not a filter.

3. FOREIGN-TITLE-FIRST CONVENTION. KG writes "Il Gattopardo AKA The Leopard".
   Searching the English title may not surface it. Mitigated by matching against
   every AKA-split part of the KG title, and by a second query pass.

Only ABSENT rows are re-checked: a better matcher can only move ABSENT->PRESENT.
"""
import json,re,sys,time,unicodedata,urllib.parse,urllib.request

B="http://192.168.10.10:9696/api/v1"; IDX=19; DELAY=2.5

def fold(s):
    s=unicodedata.normalize("NFKD",(s or "")).encode("ascii","ignore").decode()
    s=s.lower().replace("&"," and ")
    s=re.sub(r"\b(the|a|an)\b","",s)
    return re.sub(r"[^a-z0-9]+","",s)

def keys_of(t):
    out=set()
    for p in re.split(r"\s+AKA\s+|\s*/\s*",str(t),flags=re.I):
        k=fold(p)
        if len(k)>=4: out.add(k)
    k=fold(t)
    if len(k)>=4: out.add(k)
    return out

def main():
    K=open(sys.argv[3]).read().strip()
    def api(p,method="GET",body=None):
        d=json.dumps(body).encode() if body is not None else None
        r=urllib.request.Request(B+p,data=d,method=method,
            headers={"X-Api-Key":K,"Content-Type":"application/json"})
        resp=urllib.request.urlopen(r,timeout=180); t=resp.read().decode()
        return json.loads(t) if t.strip() else None
    def set_fl(v):
        i=api("/indexer/%d"%IDX)
        for f in (i.get("fields") or []):
            if f.get("name")=="freeleech": f["value"]=v
        api("/indexer/%d"%IDX,"PUT",i)
        c=api("/indexer/%d"%IDX)
        return [f.get("value") for f in (c.get("fields") or []) if f.get("name")=="freeleech"][0]

    rows=json.load(open(sys.argv[1]))
    absent=[x for x in rows if x.get("kg")=="ABSENT"]
    print("  re-checking %d ABSENT rows with corrected matcher"%len(absent),flush=True)
    restored={"d":False}
    import signal
    def restore(*a):
        if not restored["d"]:
            try: print("\n  FREELEECH RESTORED -> %s"%set_fl(True),flush=True)
            except Exception as e: print("\n  *** RESTORE FAILED: %s ***"%str(e)[:70],flush=True)
            restored["d"]=True
        if a: sys.exit(1)
    signal.signal(signal.SIGTERM,restore); signal.signal(signal.SIGINT,restore)

    def queries_for(t):
        """EVERY query string actually sent for a title. Both the control and the
        per-row loop go through here — that sharing is the whole point.

        The previous control sent a hand-written ASCII literal
        ("Celine And Julie Go Boating") while the per-row loop sent `fold(t) and t`,
        which evaluates to t, the ORIGINAL ACCENTED title: folding was computed and
        thrown away. So the control exercised a string the real path could never
        produce. It passed with 12 results while the path it guarded was broken, and
        449 rows came back ABSENT with no way to tell "not on the tracker" from
        "never actually searched for". A control whose input is not built by the
        same code as the measurement is a parallel implementation that happens to
        work; it validates nothing."""
        t=(t or "").strip()
        cand={t, fold(t), re.sub(r"[^\w\s]"," ",t), fold(re.sub(r"[^\w\s]"," ",t))}
        return sorted(q for q in cand if q.strip())

    def search(q,limit):
        try: return api("/search?"+urllib.parse.urlencode(
                {"query":q,"indexerIds":IDX,"type":"search","limit":limit}))
        except Exception: return []

    try:
        print("  freeleech -> %s"%set_fl(False),flush=True)
        # Accented ON PURPOSE. If folding regresses again, this title is queried in
        # its accented form, returns nothing, and the run ABORTS instead of emitting
        # 449 confident nulls.
        CTL="Céline And Julie Go Boating"
        ctl=[]; ctl_q=None
        for q in queries_for(CTL):
            ctl=search(q,20)
            if ctl: ctl_q=q; break
            time.sleep(DELAY)
        print("  CONTROL %r via queries_for() -> %d results %s"%(
              CTL,len(ctl),("OK (matched on %r)"%ctl_q) if ctl else "*** ABORT ***"),flush=True)
        if not ctl:
            print("  Control failed: the query builder cannot find a title the tracker"
                  "\n  demonstrably has. Every ABSENT verdict would be uninterpretable."
                  "\n  Refusing to produce a result set.",flush=True)
            return
        out=[];confirmed=0;unresolved=0
        for n,x in enumerate(absent,1):
            t=x["title"]; yr=str(x.get("year") or "")
            mine=keys_of(t)
            found=None
            # Keep hunting for a year-agreeing match even after a title-only hit:
            # every one of the 7 previous "recoveries" was a title-substring
            # collision with a different film (manifest "Heat" 1995 Michael Mann ->
            # 1972 Warhol/Morrissey "Heat"). Title alone does not identify a film.
            for q in queries_for(t):
                for r in search(q,60):
                    kk=keys_of(r.get("title"))
                    if not (mine & kk): continue
                    cand={"kg_title":r.get("title"),"seeders":r.get("seeders"),
                          "size":r.get("size"),"matched_query":q,
                          "year_agrees":bool(yr and yr in str(r.get("title")))}
                    if cand["year_agrees"]: found=cand; break
                    if found is None: found=cand      # hold as unresolved, keep looking
                if found and found.get("year_agrees"): break
                time.sleep(DELAY)

            # Three-state verdict, inseparable from the value. The old shape emitted
            # recheck:"PRESENT" with year_agrees as a SEPARATE field a reader could
            # forget to consult — and both flips were PRESENT-with-year_agrees-False,
            # i.e. non-matches indistinguishable from matches in the verdict itself.
            if found and found["year_agrees"]:
                confirmed+=1
                out.append({**x,"recheck":"PRESENT_CONFIRMED","match":found})
                print("  [%3d] PRESENT_CONFIRMED  %-32s | %s"%(n,t[:32],
                      str(found["kg_title"])[:44]),flush=True)
            elif found:
                unresolved+=1
                out.append({**x,"recheck":"PRESENT_UNRESOLVED","match":found})
                print("  [%3d] PRESENT_UNRESOLVED %-32s | %s  (year %s not in KG title"
                      " - VERIFY BY HAND)"%(n,t[:32],str(found["kg_title"])[:40],yr or "?"),
                      flush=True)
            else:
                out.append({**x,"recheck":"ABSENT"})
            if n%25==0:
                json.dump(out,open(sys.argv[2],"w"),indent=1)
                print("  [%3d/%d] confirmed=%d unresolved=%d absent=%d"%(
                      n,len(absent),confirmed,unresolved,n-confirmed-unresolved),flush=True)
            time.sleep(DELAY)
        json.dump(out,open(sys.argv[2],"w"),indent=1)
        print("\n  === RECHECK RESULT ===",flush=True)
        print("  re-checked         : %d"%len(out),flush=True)
        print("  PRESENT_CONFIRMED  : %d  <- title AND year agree; safe to act on"%confirmed,flush=True)
        print("  PRESENT_UNRESOLVED : %d  <- title matched, year did NOT. VERIFY BY HAND."%unresolved,flush=True)
        print("     (every 'recovery' in the previous run was this state: a different"
              "\n      film sharing a title fragment. Do not merge these blind.)",flush=True)
        print("  ABSENT             : %d"%(len(out)-confirmed-unresolved),flush=True)
        print("\n  ABSENT is trustworthy ONLY because the control above passed via"
              "\n  queries_for() — the same builder these rows used.",flush=True)
    finally:
        restore()

if __name__=="__main__": main()
