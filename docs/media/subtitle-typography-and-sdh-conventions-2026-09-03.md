# Subtitle typography + SDH formatting conventions — for PMP client implementation

**Date:** 2026-09-03
**Status of prior work:** research was STARTED on 2026-09-03 and never finished or applied.
**Where it must be implemented:** the CLIENT (PMP/mpv). There is nothing to apply server-side.

---

## 0. Why this was never applied — and why that was correct

The original ask was to "fix the Bazarr exporter text settings so the bitmap subs are more
readable." Three things were checked and all three came back negative:

    Bazarr styling settings    NONE  (whole settings blob searched for
                                     font/style/colour/size/outline/shadow —
                                     only `gemini_batch_size` and `page_size` matched)
    Bazarr OCR capability      NONE, and explicitly not planned upstream
    Plex server-side styling   only `SubtitlesPersistIfAdmin`

**Bazarr fetches subtitles; it never renders them.** Plex Media Server does not style text
subtitles either. Subtitle appearance is decided entirely at render time, by the player.

So this is not a server task that was skipped — it is a **client task that was misfiled as a
server task.** PMP/mpv is the only layer that can implement any of it.

The thread then pivoted to OCR (bitmap → text) and the typography work was dropped mid-flight.
Three web searches were issued (BBC accessibility subtitle guidelines, Netflix style guide,
font-size/outline specs) and never synthesised. This document is that synthesis.

---

## ⚠ 1. HARD PREREQUISITE: styling is IMPOSSIBLE on bitmap subtitles

PGS/VobSub subtitles are **pre-rendered images**. There is no text to restyle — no typeface,
no size, no colour, no outline. A player can only scale or reposition the bitmap.

That means every recommendation below applies ONLY to text subtitle formats (SRT/ASS/WebVTT).
For the ~3,451 bitmap-only titles in this library, **the OCR work is a prerequisite, not a
parallel effort** — see [[pgsocr-unconditional-invert-destroys-text]]. Until a text track
exists, no styling policy can reach those titles.

This is also why a client-side "prefer text subtitles" policy is powerless on those titles:
there is no text track to prefer.

---

## 2. LAYER ONE — typography (how the text looks)

### Typeface

The BBC broadcast standard is **Tiresias Screenfont**, designed specifically for television
legibility (large x-height, open apertures, unambiguous letterforms at low resolution and at
distance). In practice the BBC also notes the rendered font is determined by platform,
delivery mechanism, and client — i.e. the spec is advisory, not enforceable downstream.

Practical guidance for a player:

* Prefer a **humanist sans-serif with a large x-height** and disambiguated `I` / `l` / `1`.
* Avoid condensed faces, geometric sans with closed apertures, and anything with fine
  hairlines — all degrade badly against bright video and at viewing distance.
* Whatever is chosen must have a **real fallback chain**, because a missing font silently
  falls back to something unvetted.

### Size, line length, line count

* **32–37 characters per line** is the BBC/broadcaster convention.
* **Maximum 2 lines per cue.**
* Final displayed size depends on the subtitle file's instructions, the renderer, the device
  resolution, and user preference — so size should be expressed **relative to video height**,
  never in absolute pixels, or it will be wrong on one of the two displays.

> **Not confirmed:** a specific "% of screen height" figure for cap height. A commonly cited
> value is ~8%, but I could not source it directly to the BBC guidelines in this pass. Treat
> it as a starting point to tune by eye, not as a specification. Flagging rather than
> inventing a number.

### Contrast treatment

Text must survive over arbitrary video content, including white-on-white. Two established
approaches, in order of robustness:

1. **Boxed / black background band** — the BBC broadcast convention, and what its colour
   hierarchy assumes (all speaker colours are specified *on a black background only*).
   Maximum legibility, most visual intrusion.
2. **Outline + drop shadow, no box** — the streaming default. Needs a genuinely heavy border
   to survive bright scenes; a thin outline is the single most common readability failure.

---

## 3. LAYER TWO — formatting conventions by context

This is the half that actually determines whether SDH is comprehensible, and it differs by
what is being conveyed.

### 3a. Multi-character dialogue

**Colour is the BBC's preferred speaker-identification method** and should be used in most
cases. The sanctioned palette, applied in this order, **on a black background only**:

    1. white    #FFFFFF
    2. yellow   #FFFF00
    3. cyan     #00FFFF
    4. green    #00FF00   (lime)

Only a limited number of speakers can be distinguished this way; beyond four, fall back to
labels. The BBC's other sanctioned technique is **single quotes**. Other conventions appear in
legacy files and in subtitles repurposed from non-UK sources — expect inconsistency in a mixed
library.

Netflix instead uses **bracketed speaker IDs**, `[lowercase except proper nouns]`, and only
when the speaker cannot be visually identified.

**Two-speakers-in-one-cue** is conventionally marked with a leading hyphen per line:

    -Where were you?
    -Nowhere.

### 3b. Song lyrics

* Wrap lyrics in **music notes**: `♪ ... ♪` at the beginning and end of each subtitle, with a
  space between the note and the text.
* **Italicise** lyrics.
* **Duets / dual-speaker sung lines:** each line gets its own pair of notes, so it is clear
  both characters are singing.
* **Song titles in quotation marks**; **album titles in italics**.

Rendering consequence: the chosen typeface **must contain U+266A (♪)** or every lyric cue
degrades to a tofu box. This is a real and frequently-hit failure — verify the glyph exists in
the font *and* in the fallback chain.

### 3c. Soundtrack — diegetic vs non-diegetic

This distinction matters and the conventions differ:

**Non-diegetic** (score, narration, sound the characters cannot hear): conventionally
*italics*, and for music, described generically rather than transcribed unless the lyrics are
plot-relevant.

**Diegetic / ambient** (music playing in the world, from an identifiable in-scene source):
Netflix specifies a **generic ID that names the source**, e.g.

    [rock music playing over a stereo]

The source attribution is the point — it tells the viewer the sound exists *in the scene*,
which is information a hearing viewer gets for free from the mix.

### 3d. Sound effects / soundscape

* Enclosed in **square brackets** `[ ]`.
* **All lowercase**, except proper nouns.
* **Only when plot-pertinent** — and only when the sound cannot be visually identified. This
  is the rule most often violated, producing noisy captions that describe what is plainly on
  screen.

### 3e. Line-level punctuation

Netflix: uppercase letter at the beginning of each line; only question marks and exclamation
marks used as terminal punctuation within the cue.

### 3f. Further contexts worth distinct treatment

Categories beyond the four already named, each of which a viewer benefits from telling apart
at a glance:

| Context | Established convention |
|---|---|
| **Voiceover / narration** | Italics |
| **Off-screen speaker** (present but not visible) | Italics, or bracketed speaker ID |
| **Telephone / radio / PA / electronic voice** | Italics, often plus a bracketed source `[over radio]` |
| **On-screen text, signs, captions being read** | Distinct treatment; frequently ALL CAPS or top-positioned so it does not fight the pictured text |
| **Forced narrative / foreign-dialogue translation** | A *separate track class*, not SDH — see below |
| **Untranslated foreign speech** | `[speaking Russian]` rather than a transcription |
| **Shouting / whispering** | Caps for shouting in some house styles; others rely on `[shouts]` |
| **Censored / bleeped audio** | Convention varies; commonly `[bleep]` or symbol substitution |
| **Overlapping simultaneous speech** | Leading hyphens per speaker, or explicit `[overlapping]` |

**Forced narrative deserves special mention** because it is structurally different from
everything else here: it is not accessibility text but *translation of in-world text and
foreign dialogue for a hearing viewer*. It is frequently positioned near the thing it
translates (often top-of-frame to avoid burned-in signage), and a user who wants SDH styled
heavily may want forced-narrative styled minimally. Treating them as one class is a common
and visible mistake. Note this library's default-flag work already touches forced tracks —
see [[bazarr-ignore-flags-are-inverted]] and the default-flag pass.

**Two rendering-safety conditions that cut across all categories:**

* **Reading speed (CPS).** No typographic choice rescues a cue that is on screen too briefly
  to read. If a category's styling makes text larger and forces more line wraps, it can push
  a cue past the readable threshold — styling and timing interact.
* **Safe area / overscan, and the 4K↔1080p modeset.** Vertical inset must be expressed
  relative to frame height. This system changes output resolution mid-playback, so any
  absolute pixel margin will be correct on exactly one of the two paths.

---

## 4. ⚠ CAN PMP ACTUALLY DISTINGUISH THESE? — the detection matrix

This is the load-bearing question for per-category styling, and the honest answer is
**it depends entirely on the subtitle format.** Categories are *declared* in one format and
merely *inferred* in the others.

### ASS/SSA — categories are DECLARED, no guessing required

Every ASS dialogue line carries an explicit **`Style` field**:

    Dialogue: 0,0:01:22.30,0:01:24.10,Lyrics,,0,0,0,,♪ text here ♪
                                      ^^^^^^ named style, per line

The file's `[V4+ Styles]` section defines each named style. So a well-authored ASS file has
already classified its own lines, and PMP can map **style name → user preference** directly.
This is the only format where per-category styling is *reliable* rather than heuristic.

Caveats: style names are author-chosen and unstandardised (`Lyrics`, `Song`, `Karaoke`, `SFX`,
`Sign`, `Default`…), so a mapping needs fuzzy matching plus a user-visible fallback. And
overriding position-critical styles (signs, karaoke) breaks them — see the `sub-ass-override`
warning below.

### SRT / WebVTT — categories must be INFERRED from text conventions

There is no style field. Everything must be pattern-matched out of the cue text itself:

    lyrics              ♪ ... ♪   or  ♫ ... ♫          (high confidence)
    sound effect / SFX  ^\[ ... \]$  whole-cue bracket  (high confidence)
    speaker label       ^\[Name\]  or  ^NAME:           (good, but collides with SFX brackets)
    multi-speaker cue   two lines each starting "-"     (good)
    voiceover/off-screen/phone   <i>...</i>             (AMBIGUOUS — see below)

**The ambiguity that matters:** italics is overloaded. The same `<i>` marks lyrics, narration,
off-screen speech, phone audio, non-diegetic music, and emphasis. **Italics alone cannot
identify a category** — it must be combined with other signals (♪ present → lyrics; bracketed
source → device audio) and it will still be wrong sometimes.

WebVTT is slightly better: it supports **cue classes** (`<v Speaker>`, `<c.classname>`) which,
*when the authoring tool emits them*, are declarative. Most real-world VTT does not.

### PGS / VobSub — categories are UNDETECTABLE, and so is styling

Pre-rendered images. No text, no markers, no styles. Nothing to detect and nothing to restyle.
Only OCR creates a text track — and OCR output is plain SRT, so it lands in the "inferred"
tier above, *and only if the OCR preserves the markers*.

> **Consequence for our OCR pipeline, worth flagging to whoever runs it:** if OCR drops `♪` or
> mangles `[ ]`, it destroys the only signals downstream category detection has. Preserving
> those glyphs is a correctness requirement, not a nicety. The `♪` character in particular is
> exactly the kind of glyph an OCR engine silently drops.

### Summary

| Format | Category detection | Styling possible |
|---|---|---|
| ASS/SSA | **Declared** (per-line `Style`) | Yes — but overriding breaks signs/karaoke |
| WebVTT | Partial (cue classes, if authored) | Yes |
| SRT | **Inferred** (regex on ♪, `[ ]`, `-`, `<i>`) | Yes |
| PGS / VobSub | **Impossible** | **No** |

**Design implication for PMP:** a per-category styling UI is genuinely achievable, but its
reliability should be presented honestly — solid on ASS, good-but-heuristic on SRT, absent on
bitmap. A settings screen that offers per-category control and then silently fails to apply it
on a PGS track would be worse than not offering it. Consider surfacing *why* a category
control is inactive for the current track.

---

## 5. IMPLEMENTATION MAPPING — mpv (what PMP actually sets)

### The options

    sub-font              typeface (needs a real fallback chain)
    sub-font-size         scale relative to video height, not absolute px
    sub-color             primary fill
    sub-border-size       OUTLINE WEIGHT — the highest-value single setting
    sub-border-color      outline colour
    sub-shadow-offset     drop shadow distance
    sub-shadow-color      shadow colour
    sub-back-color        background band (the "boxed" BBC treatment)
    sub-margin-y          vertical safe-area inset
    sub-bold / sub-blur / sub-spacing

### ⚠ The trap: `--sub-ass-override` decides whether any of it applies

mpv converts SRT to ASS internally and its behaviour differs by source format. Values:

    no      render as the subtitle script specifies — user overrides IGNORED
    yes     apply the --sub-ass-* overrides   (DEFAULT)
    force   like yes, but ALSO force all --sub-* options — "can break rendering easily"
    scale   scaling-oriented variant
    strip   strip all ASS tags/styles (the old --no-ass)

Consequences PMP must handle deliberately:

* **For SRT** (what OCR produces, and most fetched sidecars): there is no embedded styling, so
  the `sub-*` options are what render. This is the easy case.
* **For ASS/SSA**: the file carries its own styling. Under the default, user `sub-*` settings
  may be partially or wholly ignored — this is a long-standing and repeatedly-reported source
  of confusion (mpv issues #1994, #5547; IINA #4927). `force` makes user settings win but can
  break subtitles that rely on positioning or karaoke effects.
* **Recommendation:** do NOT blanket-apply `force`. Anime and other ASS-styled content
  deliberately positions and animates text; forcing overrides there produces overlapping,
  mispositioned captions. Prefer the default for ASS, apply full styling to SRT/VTT, and if a
  user-visible "override subtitle styling" toggle is wanted, make it explicit.

### Verify before shipping

1. The chosen font is actually **present on the Pi** — a missing font falls back silently.
2. **U+266A (♪) renders** in that font and its fallbacks (test on a lyric cue).
3. The BBC speaker colours are only used **with a background band**, per the spec they come
   from — those colours are specified against black and lose contrast without it.
4. Sizing checked on **both** the 4K and 1080p paths, since the modeset changes effective
   resolution and any absolute pixel size will be wrong on one of them.

---

## 6. What is deliberately NOT claimed here

* No specific font-size percentage is asserted (see the flag in §2).
* Whether PMP currently sets any of these options at all is **unknown to me** — I have not
  read the client config. The first implementation step is to find out what is already set.
* Nothing here has been tested on the Pi. This is a synthesis of published standards plus mpv
  semantics, not a validated configuration.

---

## Sources

* [BBC Subtitle Guidelines (accessibility)](https://www.bbc.co.uk/accessibility/forproducts/guides/subtitles/)
* [BBC Subtitling Guidelines — Clevercast summary](https://www.clevercast.com/bbc-subtitling-guidelines/)
* [BBC Subtitle Style Guide 2024 — Broadcast Writer](https://broadcastwriter.com/2024/12/12/bbc-subtitle-style-guide-2024/)
* [Netflix English (USA) Timed Text Style Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide)
* [Netflix Subtitle Style Guide 2024 — Broadcast Writer](https://broadcastwriter.com/2024/12/12/netflix-subtitle-style-guide-2024/)
* [Designing Captions — typography (Kairos 23.1, Zdenek)](https://kairos.technorhetoric.net/23.1/topoi/zdenek/typography.html)
* [mpv manual](https://mpv.io/manual/master/)
* [mpv #1994 — ass-force-style ignored for SRT](https://github.com/mpv-player/mpv/issues/1994)
* [mpv #5547 — sub-ass-override=force and inline style](https://github.com/mpv-player/mpv/issues/5547)
