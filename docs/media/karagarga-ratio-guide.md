# Karagarga: ratio guide + what we measured

Two parts. **Part 1** is KG's own guidance, quoted verbatim — it is the
authoritative source and overrides anything in Part 2. **Part 2** is what this
cluster actually measured against a real account, including the places where our
own reasoning was wrong.

---

## Part 1 — KG's guidance (verbatim)

Ratio on a tracker means **(amount uploaded ÷ amount downloaded)**.

For example, if you uploaded 2GB and your total download is 4GB, your ratio is
0.5. Ideally in peer-to-peer traffic, everybody's ratio is 1 (meaning that
everybody gives back exactly what they downloaded from others). In practice,
bandwidth varies wildly among peers. Some have seedboxes, and bandwidth of home
connections varies enormously between countries and regions.

That's why at KaraGarga the ratio requirement is pretty lenient: **over time, you
need to attain a minimum ratio of 0.25.** That's the rule. The spirit is of course
to do your best to bring back to the library what you took from it: just keep
those torrents seeded, especially those that have few or no other seeders. We are
here to help each other.

### 1. Make sure your port is open

On the announce page of your active torrents, you should see your port number next
to your alias. If it says No, the tracker sees your port as closed. Trackers don't
always get it right. Canyouseeme is a reliable site to check if your port is open.
Make sure your torrent client is running when you check.

It takes several steps to open a port: set up static LAN IP; set a fixed port in
your client, and open that port in your router/modem; open that port in your
firewall. (The first step, static IP, is not always necessary.)

When your port is open, you are connectable. If it's not, you can only connect to
others whose port is open. **When you cannot open your port, like on a campus, you
have a handicap and you'll need more care and patience in the game.**

### 2. Make sure you are using a client that is allowed here

See https://karagarga.in/faq.php#clients

### 3. Don't get caught in the cookie jar

The KG library can be mouthwatering... that's the surest way to build other
people's ratio and to ruin yours. So be careful with those existing torrents, you
can wait until you can afford them.

### 4. Don't be in a big hurry

It pays to develop a feel for the kind of uploads that are popular here.

### 5. Get started

Jump as one of the first on a new upload that looks like a winner. A smallish file
is ideal for you; don't start on a dvdr unless you have high upload capacity. Upon
completion continue seeding as long as you can. Seedboxers will go away after a
while, leaving the field to you.

> **Warning.** Torrents with many leechers **and more than a day old** can be a
> ratio trap. Many such torrents contain multiple files (like extras, chapters,
> etc.). The "leechers" you see are often **partial seeders**, who de-selected
> part of the files in their client. Examples: `Jiao You AKA Stray Dogs [+Extra]`,
> `BFI Film Classics Series: 154 Titles`,
> `Charles Burnett short films + Bonus Material`.

### 6. Keep seeding

...and be patient. Especially at the start of your career, just keeping those
seeds open 24/7 will help.

### 7. Back it up

Back up everything. People will come looking for it in the future.

### 8. Upload

Get a feel for what belongs here. Make sure you know how to rip properly. Find
gems that fit here in other corners of the web. **Share after you pass the upload
threshold of 3GB** (if you have something special and you are sure it fits KG and
its rules, you can make an offer in the forum with screenshots and specs). Check
the requests regularly.

### 9. Organize

Go to your history page. At the top of your snatched torrents, click on **Lch**.
Bookmark this page.

Go to the **Reseed requests**. Click on **"You have"**. Bookmark.

### 10. Share in other ways

Make missing (English) subtitles, build a nice and useful forum collection. You
can get bonus for these things, because it's also sharing. Note available subbing
bonus on the Pots page.

### 11. Featured torrents

**Download of featured torrents does not count against your ratio.** But seeding
them can help your ratio, although you may have a lot of 'competition'. If you
have good ratio, be a sport and leave the seeding to others.

### FAQ

**Q: Help, there are many leechers but I don't connect to them.**
A: Are they downloading? Are you sure they aren't partial seeders, who only took
part of the files?

**Q: Why is my upload speed so low?**
A: Could be the other party's download speed is low. Could be you have competition
from other seeders. In a few special cases could be some other internet problem.

**Q: Why is KG such a bitch? I usually overseed on the Pirate Bay.**
A: Swarms are much smaller here. After an initial flurry, a torrent may go to
sleep for a long while. Patience is key here.

**Q: Why are so many torrents dead here?**
A: Read the KaraGarga manifesto.

---

## Part 2 — what we measured here (2026-08-10/11)

### The result

Total Deluge upload went **0.88 GB → 12.74 GB** in about a day, ~11.4 GB of it to
KG, taking the account past ratio 1.0 and clearing the 3 GB upload gate ~4x. This
was achieved with a **closed port** throughout.

### What actually blocked uploading (and what didn't)

Three hypotheses were on the table. Only one was right.

| Suspected | Verdict |
|---|---|
| Deluge version banned (KG bans <=1.20) | **No** — running 2.2.0 |
| Listen port in KG's blacklist (6881-6889) | **No** — port 54731 |
| `max_active_seeding: 5` capping seeds | **No, not at the time** — only 4 completed torrents existed, cap wasn't being hit. Raised to 50 anyway; it became load-bearing the next day at 12 concurrent seeds |
| **Radarr `removeCompletedDownloads: True`** | **YES** — Radarr reaped every torrent after import. 45 TB library, only 4 completed torrents in the client. Nothing to seed |

`removeCompletedDownloads: True` is a sane default for usenet and **actively wrong
for a private tracker**. Set it False on any torrent client used with KG.

### Demand, not configuration, is usually the reason upload is zero

The controlled comparison, same client / same tunnel / same closed port:

```
Joan of Arc of Mongolia   29 seeds,  0 leechers  ->  0 B uploaded  (9h)
King of the Hill S15       ~83 seeds, 6 leechers  ->  882 MB uploaded
Vampire's Kiss (freeleech)  1 seed,  47 leechers  ->  2.2 GB uploaded
```

A torrent with no leechers uploads nothing and that is not a fault. Before
debugging the client, check the swarm.

### Freeleech is the only ratio-positive transaction

Freeleech download adds **nothing** to the denominator while seeding adds to the
numerator, so it can only move ratio up. Best results came from stacking it with
KG's own advice — **new + freeleech + demand-heavy**:

```
Vampire's Kiss [Radiance 4K]   0d old   S=1  L=47   -> ranked 47.00 on L:S
Gwoemul AKA The Host [ProRes]  1d old   S=52 L=12   -> 0.23
The Crimson Kimono             0d old   S=119 L=10  -> 0.08
```

24h later Vampire's Kiss showed **S=110**. Arriving late would have captured
almost nothing — "seedboxers will go away after a while" cuts both ways, and the
early window is where the upload is.

Why this works with a closed port: on a fresh swarm you upload **during** the
download, because leechers trade pieces with each other and *you* initiate those
connections outbound. Seeding a completed archival torrent instead waits for an
inbound connection that a closed port never receives.

### Prowlarr's `freeleech` field is a FILTER, not a flag

Setting `freeleech: True` on the KG indexer makes **every** search return only
featured torrents. Verified: `Daisies` went 15 results -> 0.

- **Good:** Radarr/Sonarr can then never auto-grab a ratio-costing KG release.
- **Bad:** KG becomes useless for finding a specific title, and any
  "is this on KG?" audit returns a **100% false** "absent" for everything.

Always run a control query on a title known to exist before trusting a sweep.

### Cross-seeding needs bytes, not names

The info hash is computed over content, so renaming is free once bytes match — and
worthless when they don't. Exact byte-size equality is the gate; a hash recheck is
the confirmation. **Add candidates paused, force recheck, resume only at 100%** —
a mismatch otherwise silently becomes a download, which is the cookie jar in
automated form.

A 60-title title-based pilot found 0 exact matches. Note the explanation offered
at the time ("library is remuxes, KG is archival rips — different size
populations") was **wrong**: 71% of the library sits inside KG's size range. The
measurement stood; the mechanism attached to it did not.

### What Prowlarr cannot do

The Cardigann definition exposes only `search`, `movieSearch`, `musicSearch`,
`bookSearch`. There is **no requests or bounty endpoint** — the requests system and
the "Reseed requests -> You have" page must come from a browser session.

### Security

`GET /api/v1/indexer/<id>` returns the tracker **username and password in
cleartext** to any holder of the Prowlarr API key. Treat that key as equivalent to
every tracker credential Prowlarr stores.
