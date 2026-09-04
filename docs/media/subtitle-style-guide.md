# Subtitle Style Guide

**Scope:** the house standard for how subtitles should look and be marked up across this
library, what the server must do to protect that, and what the client must build to deliver it.

**Status:** server-side settings AUDITED and applied 2026-09-03. Client-side is a spec for PMP.

**Background research:** `subtitle-typography-and-sdh-conventions-2026-09-03.md`

---

## The one-paragraph version

Subtitle *appearance* is decided by the player, never by the server. The server's entire job is
to **deliver text subtitles with their semantic markers intact** — `♪` for lyrics, `[ ]` for
sound and speaker, `<i>` for off-screen/non-diegetic — because those markers are the only thing
a client can use to style categories differently. Any server-side transform that strips them
permanently destroys information the client cannot recover. The server must therefore be
*protective*, not *cosmetic*.

---

# PART 1 — THE STYLE ITSELF

## 1.1 Typography

| Property | Standard | Rationale |
|---|---|---|
| Typeface | Humanist sans, large x-height, open apertures, disambiguated `I`/`l`/`1` | BBC broadcast reference is **Tiresias Screenfont**, designed for TV legibility at distance |
| Must contain | **U+266A `♪`** in the font *and* its fallback chain | Every lyric cue renders as tofu otherwise |
| Line length | **32–37 characters** | BBC/broadcaster convention |
| Lines per cue | **2 maximum** | |
| Size | Expressed **relative to frame height**, never absolute px | This system modesets 4K↔1080p mid-playback; an absolute value is correct on exactly one path |
| Contrast | Heavy outline + shadow, or a black background band | A thin outline is the single most common readability failure |

> **Deliberately not specified:** an exact cap-height percentage. ~8% is commonly cited but I
> could not source it to the BBC guidelines directly. Tune by eye; do not encode a number we
> cannot defend.

**Background band vs outline:** the BBC speaker-colour palette below is specified *on black
only*. If colour-coding speakers, the band is not optional — those colours lose contrast
against arbitrary video without it.

## 1.2 Markup conventions by context

| Context | Convention |
|---|---|
| **Speaker ID (preferred)** | Colour, in strict order: white `#FFFFFF` → yellow `#FFFF00` → cyan `#00FFFF` → green `#00FF00`, **on a black band** |
| **Speaker ID (beyond 4, or no band)** | Bracketed label, `[lowercase except proper nouns]`, only when not visually identifiable |
| **Two speakers, one cue** | Leading hyphen per line (`-Where were you?` / `-Nowhere.`) |
| **Song lyrics** | `♪ text ♪` — note at both ends, space between note and text — **plus italics** |
| **Duet / dual sung lines** | Each line gets its own pair of notes |
| **Song / album titles** | Song in "quotes"; album in *italics* |
| **Non-diegetic** (score, narration — characters can't hear it) | *Italics*; describe generically unless lyrics are plot-relevant |
| **Diegetic / ambient music** (in-world source) | Source-naming ID: `[rock music playing over a stereo]` |
| **Sound effects** | `[lowercase brackets]`, **only when plot-pertinent and not visually obvious** |
| **Voiceover / narration** | Italics |
| **Off-screen speaker** | Italics, or bracketed ID |
| **Phone / radio / PA / electronic** | Italics + bracketed source `[over radio]` |
| **On-screen text, signs** | Distinct treatment; often top-positioned to avoid fighting burned-in text |
| **Untranslated foreign speech** | `[speaking Russian]`, not a transcription |
| **Shouting / whispering** | `[shouts]` / `[whispers]` (caps-for-shouting is a competing house style; pick one) |
| **Censored audio** | `[bleep]` or symbol substitution |
| **Overlapping speech** | Hyphens per speaker, or `[overlapping]` |
| **Punctuation** | Uppercase at line start; only `?` and `!` as terminal punctuation within a cue |

**Forced narrative is NOT SDH and must not share its styling class.** It is translation of
in-world text and foreign dialogue *for a hearing viewer*. It is often positioned near what it
translates, and a user who wants SDH styled heavily may want forced-narrative styled minimally.
Conflating them is a common and visible mistake.

**Reading speed is part of style.** Larger text forces more wraps; more wraps can push a cue
past the readable threshold. Styling and timing interact — a cue too brief to read is not
rescued by any typographic choice.

---

# PART 2 — CAN THE CATEGORIES BE DETECTED?

Per-category styling is only as good as category detection, and that splits hard by format.

| Format | Detection | Styling | Notes |
|---|---|---|---|
| **ASS/SSA** | **DECLARED** — every `Dialogue:` line carries a `Style` field | Yes | Only reliable tier. Style names are author-chosen (`Lyrics`/`Song`/`SFX`/`Sign`) → needs fuzzy mapping |
| **WebVTT** | Partial — cue classes (`<v Speaker>`, `<c.class>`) when authored | Yes | Most real-world VTT omits them |
| **SRT** | **INFERRED** — regex only | Yes | See signals below |
| **PGS / VobSub** | **IMPOSSIBLE** | **NO** | Pre-rendered images. No text, no markers, nothing to style |

**SRT inference signals, by confidence:**

    ♪ ... ♪   or  ♫ ... ♫        lyrics            HIGH
    ^\[ ... \]$  (whole cue)      sound effect      HIGH
    ^\[Name\]  or  ^NAME:         speaker label     GOOD (collides with SFX brackets)
    two lines each starting "-"   multi-speaker     GOOD
    <i>...</i>                    ???               AMBIGUOUS — DO NOT USE ALONE

**The `<i>` overload is the main trap.** Italics marks lyrics, narration, off-screen speech,
phone audio, non-diegetic music, *and* plain emphasis. It must be combined with other signals
(`♪` present → lyrics; bracketed source → device audio) and will still misfire sometimes.

**⚠ Bitmap subtitles can never be styled or categorised.** For the ~3,451 bitmap-only titles
here, OCR is a **prerequisite**, not a parallel effort — and OCR output is plain SRT, landing
in the inferred tier, *and only if OCR preserves the markers*.

---

# PART 3 — SERVER SIDE (Bazarr): PROTECT THE MARKERS

**Bazarr has no rendering settings** — it fetches and transforms subtitles, it never draws
them. Searching its settings for font/style/colour/size/outline/shadow matches only
`gemini_batch_size` and `page_size`. PMS likewise has only `SubtitlesPersistIfAdmin`.

But Bazarr **does** have a transform layer (`subzero_mods`), and that layer can destroy exactly
the markers Part 2 depends on. This is where the style guide actually binds server-side.

## 3.1 Audit result — current settings, and why each matters

    utf8_encode: true              ✅ LOAD-BEARING — this is what lets ♪ (U+266A) survive at all
    subzero_mods: common           ✅ LOAD-BEARING — see CM_music_symbols below
    hi_extension: sdh              ✅ names HI sidecars .sdh.srt — keeps SDH distinguishable
    ignore_ass_subs: true          ✅ KEEP (semantics are inverted — see below)
    ignore_pgs_subs: true          ✅ KEEP
    ignore_vobsub_subs: true       ✅ KEEP
    remove_profile_tags: []        ✅ empty — nothing being stripped
    postprocessing_cmd: ''         — unused hook, available if ever needed
    use_postprocessing: false

**`common` is actively helping and must stay enabled.** Its `CM_music_symbols` rule:

```python
NReProcessor(re.compile(r'(?u)(^[-\s>~]*[*#¶]+\s+)|(\s*[*#¶]+\s*$)'),
             lambda x: u"♪ " if x.group(1) else u" ♪", name="CM_music_symbols")
```

It **normalizes `*`, `#`, `¶` INTO `♪`** — precisely the substitutes OCR emits when it fails on
a music note. Bazarr is already repairing the marker our lyric detection depends on. This was
accidental correctness; it is now recorded intent.

## 3.2 ⛔ Mods that must NEVER be enabled

| Mod | What it does | Why it is forbidden |
|---|---|---|
| **`remove_HI`** | "Removes tags, text and characters meant for hearing impaired people". Its `HI_brackets_full` processor matches a whole `[...]`/`(...)` entry and replaces it with `""` | **Deletes every sound effect and bracketed speaker label.** Destroys SDH outright and destroys the HIGH-confidence detection signals in Part 2 |
| **`remove_tags`** | Strips formatting tags | **Destroys `<i>`** — the only signal for voiceover / phone / off-screen / non-diegetic |
| **`color`** | Writes colour into the subtitle file | Bakes one viewer's styling into shared files. Colour is a **client, per-user** decision under this guide — a server-side colour is unremovable and wrong for everyone else |

These are not stylistic preferences. `remove_HI` and `remove_tags` cause **irreversible
information loss** — once a sidecar is written without the markers, no client can recover them.

## 3.3 ✅ APPLIED 2026-09-03 — `OCR_fixes` added

    OCR_fixes — "Fix issues that happen when a subtitle gets converted from
                 bitmap to text through OCR"

Literally designed for the output of our pgsocr pipeline, and useful immediately for the many
existing sidecars that were OCR'd by their original creators. Pairs with `common`.

    subzero_mods:  common  ->  common,OCR_fixes        VERIFIED LIVE ['common','OCR_fixes']

### ⚠ How it had to be applied — `subzero_mods` is UNWRITABLE via the API/UI

Do not waste time trying to set this through the settings API or the web UI. It cannot work in
this version. In `app/config.py`:

```python
array_keys = [..., 'subzero_mods', ...]

# in the save path:
# "Make sure that text based form values aren't passed as list"
if isinstance(value, list) and len(value) == 1 and settings_keys[-1] not in array_keys:
    value = value[0]          # <-- SKIPPED, because subzero_mods IS in array_keys
```

...so the posted value stays a `list`, and is then checked against:

```python
Validator('general.subzero_mods', must_exist=True, default='', is_type_of=str)
```

**`array_keys` membership and `is_type_of=str` contradict each other, so every POST 406s** —
confirmed with both `a=common&a=OCR_fixes` (`['common','OCR_fixes']`) and a single
comma-separated value (`['common,OCR_fixes']`). Both rejected, nothing changed.

**The working procedure** (a file edit alone is NOT safe — Bazarr rewrites its config, so a
running instance can clobber it):

    kubectl scale deployment -n media bazarr --replicas=0     # stop it first
    # temp pod mounting PVC bazarr-config, edit /config/config/config.yaml
    #   subzero_mods: common  ->  common,OCR_fixes
    kubectl scale deployment -n media bazarr --replicas=1
    # verify via API that the value survived startup

Backup left at `/config/config/config.yaml.bak-styleguide-20260903`.

## 3.4 Related standing rules

* **`ignore_*_subs` semantics are INVERTED** — never flip these to `false`; it *shrinks*
  coverage. See `bazarr-ignore-flags-are-inverted`.
* **Bazarr has no OCR and never will** (upstream declined: OCR models exceed 1 GB). Bitmap →
  text must happen in our own pipeline.
* **OCR must preserve `♪` and `[ ]`.** This is a correctness requirement on the pgsocr fix, not
  a nicety — those glyphs are the client's only category signals, and `♪` is exactly what an
  OCR engine silently drops. See `pgsocr-unconditional-invert-destroys-text`.

---

# PART 4 — CLIENT SIDE (PMP): IMPLEMENTATION SPEC

## 4.1 mpv options

    sub-font              typeface (needs a real fallback chain, must include U+266A)
    sub-font-size         scale relative to frame height, NOT absolute px
    sub-color             primary fill
    sub-border-size       outline weight — highest-value single setting
    sub-border-color
    sub-shadow-offset / sub-shadow-color
    sub-back-color        background band (required if using BBC speaker colours)
    sub-margin-y          vertical safe-area inset, frame-relative
    sub-bold / sub-blur / sub-spacing

## 4.2 ⚠ `--sub-ass-override` decides whether any of it applies

    no      render as the script specifies — user overrides IGNORED
    yes     apply --sub-ass-* overrides   (DEFAULT)
    force   also forces all --sub-* options — "can break rendering easily"
    scale   scaling-oriented variant
    strip   strip all ASS tags/styles (old --no-ass)

**Do NOT blanket-apply `force`.** ASS content deliberately positions and animates (signs,
karaoke); forcing overrides produces overlapping, mispositioned captions. Recommended:
full styling on SRT/VTT, default on ASS, and any override exposed as an explicit user toggle.
Long-standing confusion: mpv #1994, #5547, IINA #4927.

## 4.3 Per-category settings UI

Users should be able to style each category distinctly **where the format permits**. Because
reliability varies by format (Part 2), the UI must be honest about it:

* **ASS** — map declared `Style` names to user preferences (fuzzy-match the common names).
* **SRT/VTT** — apply the inference signals; treat `<i>` as ambiguous.
* **PGS/VobSub** — per-category controls are **inapplicable**. Surface *why* they are inactive
  for the current track rather than silently failing to apply them. A settings screen that
  offers control it cannot deliver is worse than not offering it.

## 4.4 Pre-ship verification

1. Chosen font is actually present on the device — a missing font falls back silently.
2. **`♪` renders** in that font and its fallbacks. Test on a real lyric cue.
3. BBC speaker colours used **only with a background band**.
4. Sizing and margins verified on **both** the 4K and 1080p paths.

---

## Sources

* [BBC Subtitle Guidelines](https://www.bbc.co.uk/accessibility/forproducts/guides/subtitles/) ·
  [Clevercast summary](https://www.clevercast.com/bbc-subtitling-guidelines/) ·
  [Broadcast Writer 2024](https://broadcastwriter.com/2024/12/12/bbc-subtitle-style-guide-2024/)
* [Netflix English (USA) Timed Text Style Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide)
* [Designing Captions — typography (Kairos 23.1, Zdenek)](https://kairos.technorhetoric.net/23.1/topoi/zdenek/typography.html)
* [mpv manual](https://mpv.io/manual/master/) · [#1994](https://github.com/mpv-player/mpv/issues/1994) · [#5547](https://github.com/mpv-player/mpv/issues/5547)
* Bazarr subzero source: `/app/bin/custom_libs/subzero/modification/mods/` (read in-container 2026-09-03)
