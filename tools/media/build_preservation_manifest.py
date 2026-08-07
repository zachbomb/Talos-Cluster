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

    # ------------------------------------------------ same-name collisions
    # What motivated this: channel 20 played Rohmer's "Love in the Afternoon"
    # (1972) where Wilder's (1957) was wanted. BOTH are in the library and
    # both are correctly foldered - so no filing error exists to find, and
    # anything matching on title alone picks one of them arbitrarily. The
    # hazard is invisible until you look for names that repeat.
    #
    # Runtime separates the two very different situations that produce the
    # same folder stem:
    #   runtimes agree  -> ONE film filed under two years (a real duplicate)
    #   runtimes differ -> TWO films sharing a name (a matching hazard)
    by_stem = defaultdict(list)
    for r in rows:
        if r["tier"] != EXTRA_TIER:
            by_stem[_stem(r["folder"])].append(r)
    for stem, group in by_stem.items():
        folders = sorted({r["folder"] for r in group})
        if len(folders) < 2:
            continue
        durs = [r["duration"] for r in group if r.get("duration")]
        span = (max(durs) - min(durs)) if durs else None
        # 90 s: a festival cut vs a release cut differs by seconds, and two
        # different films sharing a title differ by far more than a minute.
        kind = "same-film" if (span is not None and span <= 90) else "distinct-works"
        for r in group:
            r["title_collision"] = {"kind": kind, "folders": folders}

    # ------------------------------------------------- filler contamination
    # Channel 20 did NOT play the wrong feature. Its FILLER pool pulled
    # featurettes belonging to a different film, because the two films share
    # a name and the filler group was keyed on that name.
    #
    # This axis has to include EXTRAs, which the deletion-gate analysis above
    # deliberately excludes. For deciding what may be deleted, a trailer is
    # not a library title. For deciding what may be used as filler, trailers
    # and featurettes ARE the entire population - so excluding them, as an
    # earlier version of this file did, makes exactly this defect invisible.
    stems_all = defaultdict(set)
    for r in rows:
        stems_all[_stem(r["folder"])].add(r["folder"])
    colliding = {s for s, f in stems_all.items() if len(f) > 1}

    for r in rows:
        if r["tier"] != EXTRA_TIER:
            continue
        risks = []
        if _stem(r["folder"]) in colliding:
            risks.append(("HIGH",
                "parent folder name collides with %s - a filler group keyed "
                "on title cannot tell these apart"
                % " / ".join(sorted(stems_all[_stem(r["folder"])] -
                                    {r["folder"]}))))
        t = (r.get("title") or "").strip()
        # A NUMBERED SEGMENT title names a distinct work ("3. AROUND PARIS"),
        # so an extra carrying one is not a trailer at all - it is another
        # film from the set, filed as this film's extra.
        #
        # A bare DISC LABEL is NOT the same thing and must not be treated as
        # one. MakeMKV stamps the disc's volume label onto every title pulled
        # off that disc, so a box-set film's own genuine trailer legitimately
        # carries the box's label. An earlier version of this check flagged
        # all 23 such extras as contamination; they are expected.
        if t and not DOTTY.match(t):
            if SEGMENT.match(t):
                risks.append(("MEDIUM",
                    "container title %r is a numbered segment - a distinct "
                    "work from the set, not a trailer for this film" % t))
            elif DISC.search(t):
                risks.append(("INFO",
                    "container title %r is the source disc's label; expected "
                    "for a box-set rip, not by itself contamination" % t))
        if any(sev in ("HIGH", "MEDIUM") for sev, _ in risks):
            r["filler_risk"] = risks

    # A file whose OWN name carries a different year than its folder - how
    # `American Woman (2019) Bluray-1080p.mkv` came to sit inside
    # `American Woman (2018)/`. A folder-level check cannot see this.
    for r in rows:
        fy = _re_fileyear.search(r["file"])
        dy = _re_folderyear.search(r["folder"])
        # If the file's year also appears in the FOLDER name, it is part of
        # the title, not a release year - `The Games of the V Olympiad
        # Stockholm, 1912 (2016)` otherwise reports a 104-year gap.
        if fy and dy and fy.group(1) != dy.group(1) \
                and fy.group(1) not in r["folder"]:
            gap = abs(int(fy.group(1)) - int(dy.group(1)))
            # A production-vs-release difference is 1-2 years and is ordinary
            # (A Single Man 2009/2010, Ex Machina 2014/2015). A larger gap is
            # not a tagging quirk - it is usually a DIFFERENT FILM sitting in
            # another film's folder. Both real instances found this way were
            # franchise cases where one title is a substring of the other
            # (`Aliens` in `Alien³`, `Blade Runner` in `Blade Runner 2049`),
            # so title prefix-matching does NOT catch them and the year gap
            # is the only signal that does.
            r["year_mismatch"] = (dy.group(1), fy.group(1), gap,
                                  "wrong-film" if gap > 2 else "year-drift")

    # Files that cannot be what they claim. Surfaced incidentally by the
    # collision scan (Le Bonheur reads 0.0 min; Long Day's Journey claims
    # 170 min in 0.25 GB) and worth reporting wherever they turn up.
    for r in rows:
        if r["tier"] == EXTRA_TIER:
            continue
        d = r.get("duration")
        if not d:
            r["implausible"] = "duration reads 0 or absent - unplayable or truncated"
        elif d > 600 and (r["size"] * 8.0 / d) < 250000:
            r["implausible"] = (
                "%.0f min in %.2f GB = %.0f kbps, too low to be intact video"
                % (d / 60.0, r["size"] / 1e9, r["size"] * 8.0 / d / 1000))
    return rows


def _stem(folder):
    """Folder name with any trailing `(year)` removed, casefolded.

    Two folders whose stems match are the same work filed twice; two whose
    stems differ are different works that happen to share a container title.
    """
    return _re_year.sub("", folder).strip().casefold()


_re_year = re.compile(r"\s*\((?:19|20)\d{2}\)\s*$")
_re_folderyear = re.compile(r"\(((?:19|20)\d{2})\)\s*$")
# A year token in a filename, parenthesised or dot/space delimited, so both
# `American Woman (2019) Bluray-1080p` and `American.Woman.2019.1080p` match.
_re_fileyear = re.compile(r"[.\s(\[]((?:19|20)\d{2})[.\s)\]]")


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

    # ------------------------------------------------ same-name collisions
    groups = {}
    for r in rows:
        tc = r.get("title_collision")
        if tc:
            groups.setdefault(tuple(tc["folders"]), (tc["kind"], []))[1].append(r)
    dupes = {k: v for k, v in groups.items() if v[0] == "same-film"}
    hazard = {k: v for k, v in groups.items() if v[0] == "distinct-works"}

    fr = [r for r in rows if r.get("filler_risk")]
    L.append("## Filler contamination — %d extras" % len(fr))
    L.append("")
    L.append("**This is what actually went wrong on channel 20.** It did not "
             "play the wrong feature — its *filler pool* served featurettes "
             "belonging to a different film, because the two films share a "
             "name and the filler group was keyed on that name.")
    L.append("")
    L.append("Extras are excluded from the deletion-gate analysis above, and "
             "correctly so: a trailer is not a library title. But for filler "
             "they are the *entire* population, so an earlier version of this "
             "generator could not see this defect at all — it dropped every "
             "`EXTRA` row before the comparison ran. Two independent risks:")
    L.append("")
    L.append("| Folder | Extra | Min | Risk |")
    L.append("|---|---|---:|---|")
    for r in sorted(fr, key=lambda r: (r["folder"], r["file"])):
        dur = "%.1f" % (r["duration"] / 60.0) if r.get("duration") else "?"
        L.append("| %s | %s | %s | %s |" % (
            r["folder"][:26], r["file"][:30], dur,
            " ; ".join("**%s** %s" % (sev, why)
                       for sev, why in r["filler_risk"])[:132]))
    L.append("")
    L.append("- **HIGH** — the extra sits in a folder whose name collides "
             "with another film's. A filler group keyed on title cannot tell "
             "them apart. **This is the channel-20 defect.**")
    L.append("- **MEDIUM** — the container title is a *numbered segment* "
             "(`3. AROUND PARIS`, `13. VISUAL ARTIST`, `5. MARRIED LIFE`), "
             "which names a distinct work from a set. An extra carrying one "
             "is not a trailer at all; it is another film filed as this "
             "film's extra.")
    L.append("")
    L.append("A bare **disc label** is deliberately *not* flagged. MakeMKV "
             "stamps the source disc's volume label onto every title pulled "
             "off it, so a box-set film's own genuine trailer legitimately "
             "carries the box's label — `8½ (1963)-trailer.mkv` reading "
             "`ESSENTIAL FELLINI - DISC 8` is expected. An earlier version of "
             "this check flagged all 23 such extras as contamination and was "
             "wrong to.")
    L.append("")

    L.append("## Same-name collisions — %d folder groups" % len(groups))
    L.append("")
    L.append("Folders whose names are identical once the year is stripped. "
             "Added after channel 20 played Rohmer's *Love in the Afternoon* "
             "(1972) where Wilder's (1957) was wanted — **both are in the "
             "library and both are correctly foldered**, so there is no filing "
             "error to find and anything matching on title alone picks one "
             "arbitrarily.")
    L.append("")
    L.append("Runtime separates the two situations that produce an identical "
             "stem: runtimes that **agree** mean one film filed under two "
             "years (a duplicate); runtimes that **differ** mean two films "
             "sharing a name (a matching hazard).")
    L.append("")

    L.append("### Same film filed under two years — %d groups. DUPLICATES."
             % len(dupes))
    L.append("")
    L.append("| Title | Folder | File | Min | GB | Tier |")
    L.append("|---|---|---|---:|---:|---|")
    for folders, (_, rs) in sorted(dupes.items()):
        for r in sorted(rs, key=lambda r: (r["folder"], r["file"])):
            dur = "%.1f" % (r["duration"] / 60.0) if r.get("duration") else "?"
            L.append("| %s | %s | %s | %s | %.2f | `%s` |" % (
                _stem(r["folder"])[:22], r["folder"][:24], r["file"][:34],
                dur, r["size"] / 1e9, r["tier"]))
    L.append("")

    L.append("### Different films sharing a name — %d groups. MATCHING "
             "HAZARD." % len(hazard))
    L.append("")
    L.append("Nothing is wrong with these on disk. They are listed because "
             "every one of them is a place where a title-based lookup — a "
             "channel lineup, an NFO match, a Plex/Emby agent — can silently "
             "resolve to the wrong film.")
    L.append("")
    L.append("| Title | Folder | Min | GB | Tier |")
    L.append("|---|---|---:|---:|---|")
    for folders, (_, rs) in sorted(hazard.items()):
        for r in sorted(rs, key=lambda r: r["folder"]):
            dur = "%.1f" % (r["duration"] / 60.0) if r.get("duration") else "?"
            L.append("| %s | %s | %s | %.2f | `%s` |" % (
                _stem(r["folder"])[:24], r["folder"][:30], dur,
                r["size"] / 1e9, r["tier"]))
    L.append("")

    ym = [r for r in rows if r.get("year_mismatch")]
    wrong = [r for r in ym if r["year_mismatch"][3] == "wrong-film"]
    drift = [r for r in ym if r["year_mismatch"][3] == "year-drift"]

    L.append("### Wrong film in the folder — %d files. FIX THESE."
             % len(wrong))
    L.append("")
    L.append("The file's own name carries a year more than 2 apart from its "
             "folder's. A production-vs-release difference is 1–2 years; a "
             "larger gap is usually a **different film sitting in another "
             "film's folder**.")
    L.append("")
    L.append("Note that both instances found this way are franchise cases "
             "where one title is a substring of the other — `Aliens` inside "
             "`Alien³`, `Blade Runner` inside `Blade Runner 2049`. Title "
             "prefix-matching does **not** catch those (`alien` is a prefix "
             "of `aliens`); the year gap is the only signal that does.")
    L.append("")
    L.append("| Folder | Contains | Gap | Min | GB |")
    L.append("|---|---|---:|---:|---:|")
    for r in sorted(wrong, key=lambda r: -r["year_mismatch"][2]):
        dur = "%.1f" % (r["duration"] / 60.0) if r.get("duration") else "?"
        L.append("| %s | **%s** | %dy | %s | %.2f |" % (
            r["folder"][:26], r["file"][:40], r["year_mismatch"][2], dur,
            r["size"] / 1e9))
    L.append("")

    L.append("### Release-year drift — %d files. NOT harmless — see below."
             % len(drift))
    L.append("")
    L.append("Gap of 1–2 years: festival vs wide release, or a differing "
             "metadata source. An earlier version of this document called "
             "these \"usually harmless\" and listed them as non-defects. "
             "**That was wrong**, and one of them proved it:")
    L.append("")
    L.append("> `School for Postmen` is recorded in Radarr as **1946**. Every "
             "release for it is labelled **1947** — as was the file that had "
             "to be deleted (`The.School.for.Postmen.1947…`). When the "
             "replacement was searched, all 18 candidate releases, including "
             "11 × Bluray-1080p, were rejected with "
             "`Unknown Movie. Unable to match to correct movie using release "
             "title`. A one-year drift made the film **unacquirable**.")
    L.append("")
    L.append("So treat this table as a latent acquisition-failure list, not "
             "noise. A drifted year is silent until the day a file needs "
             "replacing — which is exactly the day it matters.")
    L.append("")
    L.append("| Folder | File | Gap |")
    L.append("|---|---|---:|")
    for r in sorted(drift, key=lambda r: r["folder"]):
        L.append("| %s | %s | %dy |" % (
            r["folder"][:30], r["file"][:40], r["year_mismatch"][2]))
    L.append("")

    imp = [r for r in rows if r.get("implausible")]
    L.append("### Unreadable / implausible files — %d" % len(imp))
    L.append("")
    L.append("Surfaced incidentally by the collision scan. A file that cannot "
             "hold what it claims is a content problem regardless of naming.")
    L.append("")
    L.append("**Verified 2026-08-07 by re-probing every entry: 17 of 19 are "
             "genuinely corrupt**, not a probe artifact — 14 fail with "
             "`EBML header parsing failed` (the Matroska header itself is "
             "unreadable, so the file cannot be demuxed at all), plus an "
             "invalid `.iso`, a `0x0` picture size, and an EBML length error. "
             "Several are 10–45 GB. Only one reads fine; the remaining entry "
             "is the low-bitrate flag rather than a corruption.")
    L.append("")
    L.append("**These are NOT the Aug 2026 JBOD silent-checksum corruption.** "
             "16 of 19 mtimes cluster in Feb–Apr 2025, 12 in April 2025 "
             "alone. Storage corruption does not alter mtime and would hit "
             "files regardless of when they were written, scattering across "
             "the library's whole history. A tight write-time cluster of "
             "predominantly French/MULTi arthouse titles points at one bad "
             "acquisition run — corrupt on arrival, or damaged in that "
             "window. Re-acquire rather than attempting repair.")
    L.append("")
    L.append("| Folder | File | Problem |")
    L.append("|---|---|---|")
    for r in sorted(imp, key=lambda r: r["folder"]):
        L.append("| %s | %s | %s |" % (
            r["folder"][:28], r["file"][:32], r["implausible"][:64]))
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
