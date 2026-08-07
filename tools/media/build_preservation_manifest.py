#!/usr/bin/env python3
"""Build the SQ-8 preservation manifest from a library-wide ffprobe census.

WHY THIS EXISTS
---------------
Two planning documents gate irreversible deletions on a manifest that did not
exist:

  docs/media/remediation-plan-2026-08-04.md:326
      "Cross-check the 4.0 GB rip against the SQ-8 household disc-rip
       preservation manifest before destroying it"

  docs/media/quarantine-decisions-research.md:183
      "No such manifest exists under `docs/` in this repo (searched)"

SQ-8's board record is a title and nothing else - no body, no description, no
comments. Its claim of a "manifest complete (5,117 files)" was never persisted
anywhere. So D9, D10 and the line-464 item are all blocked on a lookup that is
impossible to perform. This script makes it performable.

WHAT THE MANIFEST DOES AND DOES NOT CLAIM
-----------------------------------------
It does NOT claim household provenance. A disc label in a container proves the
file came from *a* disc; it cannot prove it came from *this household's* disc,
because a downloaded box-set rip retains its label too. Any manifest asserting
otherwise would be confidently wrong in exactly the situation it is consulted -
authorising or forbidding a deletion.

What it does claim is narrower and defensible: whether there is positive
evidence that a file is IRREPLACEABLE, REPLACEABLE, or neither.

That is sufficient for the decision the plan docs actually need to make. D9 and
D10 fail the same way: a file is read as "a redundant duplicate of the movie in
this folder" and deleted. A disc label refutes that reading directly. "Disc 29
of 100 Years of Olympic Films" is not a duplicate of the movie it is filed
under, whoever ripped it.

THE DISCRIMINATOR
-----------------
Scene releases are dot-delimited and carry encoding tokens (1080p, BluRay,
x264). MakeMKV writes the disc's volume label - space-delimited human text,
frequently ALL CAPS - into format_tags.title.

Matching on vocabulary rather than delimiter is the trap. An early pass keyed on
the word "Criterion" and pulled in
`Black.Panthers.1968.Criterion.1080p.BluRay.x264` - a scene release of a
Criterion disc, freely re-downloadable. Padding a preservation manifest with
replaceable files is not a harmless error: it is what makes the manifest
untrustworthy for the one job it has.

USAGE
-----
    python3 tools/media/build_preservation_manifest.py rip-census.json

Writes docs/media/preservation-manifest.{md,json}.
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

# ---------------------------------------------------------------- classifiers

# WEB sources. A file from these CANNOT be a rip of a disc anyone owns - the
# source is a streaming service, not physical media. This is the one signal
# here that rests on how the file came to exist rather than on how it was
# named, which is why it is the only one trusted to mark a file deletable on
# its own.
WEB_SOURCE = re.compile(
    r"(?i)\b(WEB-?DL|WEBRip|WEB|HDTV|PDTV|AMZN|DSNP|NF|HMAX|ATVP|PCOK|"
    r"iP|STAN|CRAV)\b")

# Disc sources. Compatible with owning the disc - these do NOT establish that
# a file was downloaded.
DISC_SOURCE = re.compile(r"(?i)\b(BluRay|Blu-Ray|BDRip|BRRip|BD25|BD50|"
                         r"DVD|DVDRip|NTSC|PAL|REMUX)\b")

# Quality/codec tokens alone. Radarr's rename template stamps these onto
# EVERY file it imports, household rips included, so on their own they say
# nothing about origin. Retained only to explain a REVIEW verdict.
QUALITY_TOK = re.compile(
    r"(?i)\b(1080p|2160p|720p|480p|x264|x265|HEVC|AVC|DTS|DDP?5|EAC3|"
    r"AAC2?|HDR10?|DV|SDR|10bit|8bit|Proper|REPACK)\b")

# Three or more dot-separated runs with no whitespace: scene naming.
DOTTY = re.compile(r"^[^\s]+\.[^\s]+\.[^\s]+")

# A release-group suffix, and ONLY in the two forms that actually mark one:
# after a closing bracket (`[HEVC]-GROUP`) or ending a dot-scene name
# (`...DTS-HD.MA.5.1-SWTYBLZ`). A bare `-word$` arm was tried and discarded -
# it matched 109 files, of which the first was `12 Angry Men (1957)-trailer`.
GROUP = re.compile(r"[\]\)]\s*-\s*([A-Za-z0-9_.]{2,20})$")
GROUP_DOT = re.compile(r"^[^\s]+\.[^\s]+.*-([A-Za-z0-9_]{2,20})$")

# Extras. Not library titles - they must not enter the manifest population at
# all, or they inflate every count and bury the files that matter.
EXTRA = re.compile(r"(?i)-(trailer|sample|featurette|interview|scene|short|"
                   r"behindthescenes|deleted|other|clip|teaser)$")

# "Disc 3", "DISC 02", "Disk 1" - a disc within a set.
DISC = re.compile(r"(?i)\bdis[ck]\s*0*(\d{1,2})\b")

# "8. NO SHELTER", "14. HERE AND THERE" - a numbered track within a set.
SEGMENT = re.compile(r"^\s*(\d{1,2})\s*[.\-]\s+\S")

# Tiers, most protective first.
PROTECTED = "PROTECTED"        # positive evidence the file is irreplaceable
REPLACEABLE = "REPLACEABLE"    # positive evidence the file can be re-acquired
REVIEW = "REVIEW"              # no positive evidence either way
EXTRA_TIER = "EXTRA"           # not a library title; excluded from the gate


def has_group(text):
    """True when `text` ends in a release-group suffix."""
    if not text:
        return False
    t = text.strip()
    return bool(GROUP.search(t)) or bool(GROUP_DOT.match(t))


def classify(rec):
    """Return (tier, evidence-string) for one census row.

    Evidence is a sentence a human can act on, not a code - the manifest is
    consulted at the moment someone is about to delete something, and a bare
    enum does not tell them why.
    """
    title = (rec.get("title") or "").strip()
    fname = os.path.splitext(rec.get("file", ""))[0]
    both = title + " || " + fname

    # 0. Extras are not library titles. Excluding them keeps the gate's counts
    #    about the files a deletion decision could actually destroy.
    if EXTRA.search(fname):
        return EXTRA_TIER, "extra (trailer/featurette/sample), not a library title"

    # 1. A WEB source settles it, and outranks every naming signal below,
    #    because it is an argument about physics rather than convention: you
    #    cannot produce a WEB-DL from a disc in your hand. Checked first so
    #    that a stray disc-shaped container title cannot protect a file that
    #    provably came off a streaming service.
    web = WEB_SOURCE.search(both)
    if web:
        return REPLACEABLE, (
            "source token %r - a WEB source cannot be a rip of a disc anyone "
            "owns, so this file is re-acquirable by definition"
            % web.group(1))

    # 2. A disc or track label the release pipeline did not write. This is the
    #    class that refutes "redundant duplicate of the movie in this folder".
    disc = DISC.search(title) if title else None
    seg = SEGMENT.match(title) if title else None
    dotty = bool(DOTTY.match(title)) if title else False

    if disc and not dotty:
        return PROTECTED, (
            "container title %r names disc %s of a multi-disc set; this file "
            "is one disc of that set, not a copy of the movie it is filed "
            "under" % (title, disc.group(1)))
    if seg and not dotty:
        return PROTECTED, (
            "container title %r is numbered track %s of a set; deleting it "
            "removes one segment, not a duplicate" % (title, seg.group(1)))

    # 3. A disc source WITH a release-group suffix is somebody's published rip
    #    of a disc - re-acquirable. Without a group it is not, because Radarr
    #    stamps disc-source tokens onto household rips too.
    src = DISC_SOURCE.search(both)
    if has_group(fname) or dotty:
        return REPLACEABLE, (
            "filename carries a release-group suffix (%s) - a published "
            "release, re-acquirable" % fname[-28:])

    # 4. No positive evidence in either direction. Spell out which flavour,
    #    because the three read very differently to whoever is deciding.
    srctxt = (" ; disc-source token %r present" % src.group(1)) if src else ""

    if src and QUALITY_TOK.search(both):
        return REVIEW, (
            "disc-source token %r with quality tokens but NO release group - "
            "consistent with a household rip that Radarr renamed on import; "
            "Radarr stamps these tokens onto every file it manages, so they "
            "are not evidence of a download" % src.group(1))

    # An ISO-9660 volume ID is uppercase-restricted, so a MakeMKV disc label
    # arrives ALL CAPS far more often than a typed movie title would. Not
    # enough to protect on its own - there is no set membership to point at -
    # but it is the difference between a blind review pass and a directed one.
    if title and title.isupper() and len(title) > 3:
        return REVIEW, (
            "container title %r is ALL CAPS, the shape of an ISO-9660 volume "
            "label rather than a typed movie title - leans disc rip, but "
            "carries no disc number to prove set membership%s"
            % (title, srctxt))

    if title:
        return REVIEW, (
            "container title %r is plain human text - no disc number, no "
            "release group%s; could be a single-disc rip or a retitled "
            "download" % (title, srctxt or ", no source token"))
    return REVIEW, (
        "no container title tag%s; provenance not determinable from metadata "
        "alone" % (srctxt or " and no source or group token"))


# ---------------------------------------------------------------------- build

def build(rows):
    for r in rows:
        r["tier"], r["evidence"] = classify(r)

    # Same-folder duration collisions: two files of near-identical length in
    # one folder is the shape that reads as "duplicate" and triggers deletion.
    # Flagging it does not resolve it - it marks where the manifest is being
    # asked the question it exists to answer.
    by_folder = defaultdict(list)
    for r in rows:
        r["duration_collision"] = False
        r["folder_video_count"] = 0
        if r["tier"] != EXTRA_TIER:      # a trailer is never the duplicate
            by_folder[r["folder"]].append(r)
    for folder, group in by_folder.items():
        for a in group:
            a["folder_video_count"] = len(group)
            if a.get("duration") is None:
                continue
            for b in group:
                if b is a or b.get("duration") is None:
                    continue
                if abs(a["duration"] - b["duration"]) <= 30:
                    a["duration_collision"] = True
                    break

    # Cross-folder twins. D10 is exactly this shape and per-folder matching is
    # blind to it: `JOUR DE FÊTE DANS LES MONTS NAGA (1964)` and `(1995)` are
    # separate folders holding one file each, both titled `JOUR DE FÊTE`,
    # 80.5 vs 80.3 min. Duration alone across 2,400 files would pair unrelated
    # films of similar length, so the key is an IDENTICAL container title plus
    # durations within 60 s - specific enough to mean something.
    by_title = defaultdict(list)
    for r in rows:
        t = (r.get("title") or "").strip()
        if t and r["tier"] != EXTRA_TIER:
            by_title[t].append(r)
    for t, group in by_title.items():
        folders = {r["folder"] for r in group}
        if len(folders) < 2:
            continue
        for a in group:
            if a.get("duration") is None:
                continue
            twins = [b for b in group
                     if b is not a and b["folder"] != a["folder"]
                     and b.get("duration") is not None
                     and abs(b["duration"] - a["duration"]) <= 60]
            if twins:
                a["cross_folder_twin"] = sorted(b["folder"] for b in twins)
    return rows


def _stem(folder):
    """Folder name with any trailing `(year)` removed, casefolded.

    Two folders whose stems match are the same work filed twice; two whose
    stems differ are different works that happen to share a container title.
    """
    return _re_year.sub("", folder).strip().casefold()


_re_year = re.compile(r"\s*\((?:19|20)\d{2}\)\s*$")


def render_md(rows):
    tiers = Counter(r["tier"] for r in rows)
    protected = sorted((r for r in rows if r["tier"] == PROTECTED),
                       key=lambda r: (r["folder"], r["file"]))
    collisions = sorted((r for r in rows if r.get("duration_collision")),
                        key=lambda r: r["folder"])

    L = []
    L.append("# SQ-8 preservation manifest")
    L.append("")
    domains = sorted({r.get("domain", "?") for r in rows})
    folders = len({r["folder"] for r in rows})
    L.append("Generated by `tools/media/build_preservation_manifest.py`. Do "
             "not hand-edit; re-run the generator.")
    L.append("")
    L.append("**Scope: %s only** — %d files across %d folders, every one "
             "probed with `ffprobe` for its container title and duration. TV, "
             "music and books are **not** covered and must not be assumed "
             "cleared by this file. The deletion gates that motivated it (D9, "
             "D10) are all movie-side; extending it is a matter of adding "
             "roots to the census script."
             % ("/".join(domains), len(rows), folders))
    L.append("")
    L.append("## What this is for")
    L.append("")
    L.append("`docs/media/remediation-plan-2026-08-04.md` gates the D9 and D10 "
             "deletions on \"the SQ-8 household disc-rip preservation "
             "manifest\". Until now that manifest did not exist "
             "(`docs/media/quarantine-decisions-research.md:183`), so the gate "
             "could not be cleared and the deletions could not proceed. This "
             "file is that gate.")
    L.append("")
    L.append("## What it claims, and what it does not")
    L.append("")
    L.append("It does **not** assert household provenance. A disc label proves "
             "a file came from *a* disc, not from *this household's* disc - a "
             "downloaded box-set rip carries the same label. Asserting "
             "otherwise would make the manifest wrong precisely when it is "
             "consulted.")
    L.append("")
    L.append("It asserts something narrower and checkable: whether there is "
             "positive evidence a file is irreplaceable, replaceable, or "
             "neither. That is enough for the decision the plan documents "
             "need, because D9 and D10 both fail the same way - a file is read "
             "as a redundant duplicate of the movie in its folder and deleted. "
             "A disc label refutes that reading regardless of who ripped it.")
    L.append("")
    L.append("| Tier | Meaning | Action |")
    L.append("|---|---|---|")
    L.append("| `PROTECTED` | Container title names a disc or numbered track "
             "of a set, with no release-pipeline tokens. | **Never delete as a "
             "duplicate.** It is part of a set. |")
    L.append("| `REPLACEABLE` | Title or filename carries release tokens "
             "(`1080p`, `BluRay`, `x264`, …). | Safe to delete; re-acquirable. |")
    L.append("| `REVIEW` | No positive evidence either way. | Human decision "
             "required. Default to keeping. |")
    L.append("| `EXTRA` | Trailer, sample, featurette. Not a library title. | "
             "Outside the gate. |")
    L.append("")
    L.append("### How replaceability is established")
    L.append("")
    L.append("Only two things mark a file deletable, and neither is a naming "
             "convention on its own:")
    L.append("")
    L.append("1. **A WEB source token** (`WEB-DL`, `WEBRip`, `HDTV`, `AMZN`, "
             "`DSNP`, …). This is an argument about physics, not naming: you "
             "cannot produce a WEB-DL from a disc in your hand. It outranks "
             "every other signal.")
    L.append("2. **A release-group suffix** (`[HEVC]-GROUP`, or a dot-scene "
             "name ending `-GROUP`). Somebody published this; it can be "
             "fetched again.")
    L.append("")
    L.append("Quality and codec tokens (`1080p`, `x264`, `Bluray-1080p`) are "
             "explicitly **not** sufficient. Radarr's rename template stamps "
             "them onto every file it imports, household rips included, so "
             "they describe the encode rather than the origin. An earlier "
             "draft of this generator treated them as sufficient and marked "
             "`12 Angry Men (1957) {tmdb-389} [Remux-2160p]…` replaceable on "
             "that basis alone.")
    L.append("")
    L.append("The two error directions are not symmetric. A wrong `PROTECTED` "
             "costs disk. A wrong `REPLACEABLE` authorises destroying "
             "something irreplaceable, which is the only thing this file "
             "exists to prevent - so every rule above is biased toward "
             "`REVIEW`.")
    L.append("")
    L.append("## Census")
    L.append("")
    L.append("| Tier | Files |")
    L.append("|---|---:|")
    for t in (PROTECTED, REPLACEABLE, REVIEW, EXTRA_TIER):
        L.append("| `%s` | %d |" % (t, tiers.get(t, 0)))
    L.append("| **total** | **%d** |" % len(rows))
    L.append("")

    L.append("## PROTECTED — %d files" % len(protected))
    L.append("")
    L.append("These carry a disc or track number in the container title with "
             "no release-pipeline tokens. Each is one part of a multi-part "
             "set. None of them is a duplicate of the movie in its folder.")
    L.append("")
    L.append("| Folder | File | Container title | Min |")
    L.append("|---|---|---|---:|")
    for r in protected:
        dur = "%.1f" % (r["duration"] / 60.0) if r.get("duration") else "?"
        L.append("| %s | %s | `%s` | %s |" % (
            r["folder"][:44], r["file"][:44], r.get("title", "")[:46], dur))
    L.append("")

    review = sorted((r for r in rows if r["tier"] == REVIEW),
                    key=lambda r: (r["folder"], r["file"]))
    caps = [r for r in review if "ALL CAPS" in r["evidence"]]
    norip = [r for r in review if "renamed on import" in r["evidence"]]

    L.append("## REVIEW — %d files needing a human decision" % len(review))
    L.append("")
    L.append("Two sub-classes are worth pulling out, because they are not "
             "equally uncertain:")
    L.append("")
    L.append("- **%d files with an ALL-CAPS container title.** An ISO-9660 "
             "volume ID is uppercase-restricted, so a disc label arrives ALL "
             "CAPS far more often than a typed movie title does. No disc "
             "number means no set membership to prove, so these cannot be "
             "`PROTECTED` - but they are the likeliest disc rips in this "
             "list." % len(caps))
    L.append("- **%d files carrying a disc-source token and quality tokens "
             "but no release group.** Consistent with a household rip that "
             "Radarr renamed on import." % len(norip))
    L.append("")
    L.append("| Folder | Container title | Min | Why it is unresolved |")
    L.append("|---|---|---:|---|")
    for r in review:
        dur = "%.1f" % (r["duration"] / 60.0) if r.get("duration") else "?"
        L.append("| %s | `%s` | %s | %s |" % (
            r["folder"][:34], (r.get("title") or "—")[:30], dur,
            r["evidence"][:96]))
    L.append("")

    L.append("## Same-folder duration collisions — %d files" % len(collisions))
    L.append("")
    L.append("Two or more files within 30 s of each other in one folder. This "
             "is the shape that reads as \"duplicate\" and triggers a "
             "deletion, so it is where the manifest is most likely to be "
             "consulted. The tier column is the answer.")
    L.append("")
    L.append("| Folder | File | Tier | Min |")
    L.append("|---|---|---|---:|")
    for r in collisions:
        dur = "%.1f" % (r["duration"] / 60.0) if r.get("duration") else "?"
        L.append("| %s | %s | `%s` | %s |" % (
            r["folder"][:40], r["file"][:40], r["tier"], dur))
    L.append("")

    twins = sorted((r for r in rows if r.get("cross_folder_twin")),
                   key=lambda r: ((r.get("title") or ""), r["folder"]))
    same_disc = [r for r in twins if DISC.search(r.get("title") or "")]
    maybe_dup = [r for r in twins if not DISC.search(r.get("title") or "")]

    L.append("## Cross-folder twins — %d files" % len(twins))
    L.append("")
    L.append("Files in **different folders** sharing an identical container "
             "title and a runtime within 60 s. Per-folder duplicate detection "
             "cannot see these, and D10 is exactly this shape.")
    L.append("")
    L.append("> **Read this before deleting anything from the tables below.** "
             "An identical container title across folders does **not** mean "
             "duplicate content. For a box set it usually means the opposite: "
             "same source disc, *different films*. The two tables are split "
             "on that distinction and must be treated as opposites.")
    L.append("")

    L.append("### Same source disc, distinct works — %d files. DO NOT "
             "DEDUPE." % len(same_disc))
    L.append("")
    L.append("The shared title carries a **disc number**, so these files came "
             "off one disc of a set and each is a different work. `Lost "
             "Keaton Disc 1` appears under four folders because disc 1 holds "
             "four separate Keaton shorts, each extracted and filed as its "
             "own title. They are identical in label and near-identical in "
             "runtime and size, which is exactly what a naive duplicate sweep "
             "keys on - and deleting the \"extras\" would destroy three "
             "distinct films.")
    L.append("")
    L.append("| Container title | Folder (the actual film) | Min | GB |")
    L.append("|---|---|---:|---:|")
    for r in sorted(same_disc, key=lambda r: ((r.get("title") or ""),
                                              r["folder"])):
        dur = "%.1f" % (r["duration"] / 60.0) if r.get("duration") else "?"
        L.append("| `%s` | %s | %s | %.2f |" % (
            (r.get("title") or "")[:26], r["folder"][:40], dur,
            r["size"] / 1e9))
    L.append("")

    L.append("### No disc number — possible genuine duplicate — %d files"
             % len(maybe_dup))
    L.append("")
    L.append("The shared title carries no disc number, so there is no set "
             "membership to explain the repetition. This is the D10 shape: "
             "two folders differing only by year, one file each, same title, "
             "runtimes 80.5 vs 80.3 min. Still a human decision - note the "
             "tier, since a duplicate of something irreplaceable is not the "
             "same as a duplicate of something you can fetch again.")
    L.append("")
    L.append("A shared title with **no** disc number still does not settle it, "
             "because a compilation disc can be labelled without one. `TATI "
             "SHORTS` is exactly that: `Evening Classes (1967)` and `Forza "
             "Bastia (1978)` are two different Tati shorts off one disc, not "
             "two copies of anything. The folder names discriminate - strip "
             "the year and compare what is left:")
    L.append("")
    L.append("- **same work** (folder stems match, differing only by year) → "
             "genuine duplicate candidate. `JOUR DE FÊTE DANS LES MONTS NAGA` "
             "(1964) vs (1995).")
    L.append("- **different works** (folder stems differ) → distinct films "
             "sharing a compilation label. Not duplicates.")
    L.append("")
    L.append("| Container title | Folder | Same work? | Tier | Min | GB |")
    L.append("|---|---|---|---|---:|---:|")
    for r in sorted(maybe_dup, key=lambda r: ((r.get("title") or ""),
                                              r["folder"])):
        dur = "%.1f" % (r["duration"] / 60.0) if r.get("duration") else "?"
        stem = _stem(r["folder"])
        same = any(_stem(t) == stem for t in r["cross_folder_twin"])
        verdict = ("**YES — duplicate candidate**" if same
                   else "no — distinct works, do not dedupe")
        L.append("| `%s` | %s | %s | `%s` | %s | %.2f |" % (
            (r.get("title") or "")[:22], r["folder"][:30], verdict,
            r["tier"], dur, r["size"] / 1e9))
    L.append("")
    return "\n".join(L) + "\n"


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    census = json.load(open(sys.argv[1]))
    if census.get("partial"):
        print("WARNING: census is partial (%d rows) - manifest will be "
              "incomplete" % census["n"], file=sys.stderr)
    rows = build(census["rows"])

    here = os.path.dirname(os.path.abspath(__file__))
    outdir = os.path.abspath(os.path.join(here, "../../docs/media"))
    md = os.path.join(outdir, "preservation-manifest.md")
    js = os.path.join(outdir, "preservation-manifest.json")

    text = render_md(rows)          # render before truncating either file
    open(md, "w").write(text)
    json.dump({"generated_from": os.path.basename(sys.argv[1]),
               "partial": census.get("partial"),
               "count": len(rows),
               "rows": rows}, open(js, "w"), indent=1)

    tiers = Counter(r["tier"] for r in rows)
    print("wrote %s" % md)
    print("wrote %s" % js)
    for t in (PROTECTED, REPLACEABLE, REVIEW):
        print("  %-12s %d" % (t, tiers.get(t, 0)))


if __name__ == "__main__":
    main()
