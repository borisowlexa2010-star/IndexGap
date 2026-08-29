# indexgap

**Lint your programmatic SEO pipeline — from keywords to indexed pages.**

> [Русская версия](README.ru.md)

You generated three thousand pages from a dataset. They're on disk, they're in
the sitemap, and there's no traffic. `indexgap` tells you where they were lost.

Pure Python 3.9+ standard library. No dependencies, no API keys, no paid
subscriptions. Nothing leaves your machine without an explicit flag.

---

## Why this exists

Plenty of tools audit *a page*. A generated pipeline breaks differently —
systematically and quietly:

* a page is in the sitemap, but no internal link points to it, so the crawler
  never arrives;
* three hundred pages differ by five words, and the search engine keeps one;
* the model wrote "12 years in business" and "3,500 orders" — neither number
  exists in any row of your data, but it reads convincingly;
* `lastmod` equals the build date on every page, so it means nothing;
* two keywords with the same intent produced two competing pages.

None of this is visible page by page. Each one looks fine on its own.

---

## Install

```bash
pip install indexgap
```

Then, once per project:

```bash
cd ~/projects/my-site
indexgap init
```

`init` reads the project and records what makes it different: where the pages
are, the site URL, the content type, the dataset. It installs skills into
`.claude/skills/` so your coding agent picks them up on its own, and adds the
working files to `.gitignore`.

Nothing project-specific is ever copied between projects — it is detected
fresh each time. **The IndexNow key in particular is never carried over:**
it is bound to one domain by a file at that site's root, and a borrowed key
returns 403. `indexgap init --key` mints a new one for this project.

After that, the daily command is just:

```bash
indexgap check
```

---

## Commands

```bash
indexgap init                       # install into this project
indexgap plan keywords.csv          # audit the keyword set before generating
indexgap check                      # everything local: text, structure, machine-readability
indexgap sitemap --out-dir ./public # sitemap with sharding and an honest lastmod
indexgap notify --key <your-key>    # tell IndexNow what actually changed
indexgap doctor --sitemap ./public/sitemap.xml --indexed gsc.csv
indexgap portfolio projects.json    # every site you own, in one run
indexgap profiles                   # what the content-type presets change
```

Understands both built HTML and Markdown sources with frontmatter. Input file
encoding is detected, not assumed: UTF-16, BOM, and the cp1251 CSVs that
Russian Excel produces all read correctly. Exports are read as they come —
CSV with any delimiter, XLSX straight from Ahrefs or Semrush without
re-saving, JSON, NDJSON, an XML sitemap, or a plain list of URLs — and the
keyword column is found whether the export calls it `Keyword`, `Фраза`,
`Запрос` or `Search Term`.

---

## What it checks

**Before generating** — exact duplicate keys, slug collisions and *same-intent*
keys. That last one matters most: two keywords meaning the same thing will
produce two competing pages, and it is cheaper never to create the second.

**After generating — the text**

| Check | Why it matters |
|---|---|
| **Numbers absent from your data** | prices, terms and counts are verified against the source row. A number that appears nowhere in the dataset is never forgiven, no matter how many pages repeat it |
| Identical heading skeletons | different words, same structure — a stamping tell |
| Identical opening sentences | the second tell |
| Leftover brief, `status: draft` | unfinished pages never reach the sitemap or the IndexNow queue |
| "Click here" anchors | a link with no meaning in it |

**After generating — the structure**

Near-duplicates (exact pairwise below 400 pages, MinHash + LSH above), share of
unique text measured *by bigrams* rather than words, thin pages, orphans,
click depth, `noindex`, `nosnippet`, foreign canonicals, missing or duplicate
H1, duplicate titles and descriptions.

**Machine readability for AI search**

Snippet controls (`nosnippet`, `max-snippet:0`), `robots.txt` rules for
OAI-SearchBot, PerplexityBot, ClaudeBot, GPTBot and Google-Extended (they are
not interchangeable — blocking OAI-SearchBot removes you from ChatGPT search
answers, while Google-Extended does not affect AI Overviews), empty JS shells,
a direct answer in the first paragraph, question-shaped subheadings, valid
JSON-LD that matches the visible text, machine-readable dates and author.

**At publish time** — sitemap sharding past 45,000 URLs and a `lastmod` that
changes only when the text, title or description changed. Editing one menu item
does not mark the whole site as modified. IndexNow sends only what changed.

---

## The funnel

The reason to install it at all:

```
Generated                 58
Indexable                 56   (−2: noindex or a canonical pointing elsewhere)
In sitemap                56
In at least one index     28   (−28: the engine knows the URL and didn't add it)

Why pages are not indexed:
    7  orphaned or unreachable  → link them from hub pages
   12  deeper than the click budget → move them up
    9  no local explanation → check status in Search Console
```

Index data comes from ordinary exports — no API keys. A webmaster panel is the
direct source (Search Console, Bing Webmaster Tools, Yandex.Webmaster, Naver,
Seznam), but not everyone has one, so exports from **Ahrefs, Semrush, Serpstat,
Moz, Screaming Frog, Sitebulb, JetOctopus, OnCrawl, Netpeak, GA4, Matomo,
Plausible** — or a plain list of URLs — are read too, in CSV, XLSX, JSON,
NDJSON or XML.

They are not interchangeable, and the tool refuses to pretend otherwise. A
panel answers "does the engine know this page". Analytics proves a page is
indexed, but only for pages someone actually visited — its silence proves
nothing. A crawler proves reachability, not indexation. Ahrefs and Semrush are
*their* index, not Google's. So the funnel step is renamed to match the
evidence — "at least in one index" versus "known to a third-party service" —
and when a crawler export sits next to a panel, the report says out loud that
the step count is higher than real indexation. Engine-vs-engine comparison
runs over panels only.

**Ask for all the panels you have, not just Google.** A page missing *everywhere* is a technical problem. A page missing
*only in one engine* was crawled and accepted by the others, which makes it a
quality or speed question that technical fixes rarely solve. Without the split
the two look identical and people fix the wrong thing.

One honest caveat the tool states out loud: the Search Console "Pages" export
is an *impressions* report, not an index report. A page that is indexed but has
no impressions won't appear in it, so on a young site the funnel overstates
losses.

---

## Content-type profiles

Thresholds differ across content types by substance, not taste. 250 words is
normal for a guide and absurd for an event card; fact-checking is meaningless
where there is no dataset at all.

| Profile | For | What changes |
|---|---|---|
| `catalog` | pages generated from data rows | fact-checking is primary; duplicate threshold 0.80; thin under 250 words |
| `events` | listings, schedules, venues | threshold 0.88 — two dates of one tour are legitimately similar; adds `stale-event` |
| `ugc` | feeds, threads, reviews | fact-checking is switched off *and says so*; threshold 0.92 |
| `product` | dozens of landing pages, not thousands | duplicates aren't the issue; the AI-readability checks are |

`stale-event` catches an event whose date has passed while the page stays open
to indexing. That isn't a traffic problem, it's a trust problem: someone drives
to a concert that no longer exists.

For `ugc`, silence is not a clean bill of health — it means there was nothing to
check against, and the tool prints that as a line rather than leaving you to
assume.

---

## Portfolio

Separate reports answer "what's wrong with this site". A portfolio answers the
question you can't see in them: **what breaks the same way everywhere.**

```
  · visa       2933 pages  critical  412  [catalog]
  · events      840 pages  critical   61  [events]
  · feed       5100 pages  critical    0  [ugc]
  · product      34 pages  critical    2  [product]

Shared problems, as a share of each project's pages:
  orphan        3 projects: visa 41%, events 38%, product 35%
  same-opening  2 projects: visa 62%, events 55%
```

Shares, not counts: a hundred findings across three thousand pages and ten
across twenty are the same disease at different volumes. One project failing
doesn't stop the run — it becomes a line in the report.

---

## What it does *not* claim

It does not promise citations in AI search, and it says so in the output.
Ahrefs, across 75,000 brands, found AI visibility correlates most with mentions
*off* your site (0.66–0.74) and with page count at **0.19** — which is exactly
what a programmatic pipeline produces. 76% of AI Overview citations come from
pages already ranking in the classic top 10.

So: machine readability is a necessary condition and this tool's job. Getting
cited is decided by work outside your files, and that is not a code problem.

No `llms.txt` generator either. Google has stated it does not support it and
has no plans to; no engine has confirmed using it for ranking. Generating a
file nobody reads is a ritual, not a feature.

It also doesn't write or rewrite content, check rankings, or call paid services.
Rejecting keywords and acting on contested findings is always confirmed by a human.

And it does not replace Search Console — it leads you there. If the tool says
one thing and Search Console says another, Search Console is right.

---

## Tests

```bash
python3 -m unittest discover -s tests
```

217 scenarios. Each one is a reproduced defect found by two waves of adversarial
review and one run against six live sites, plus the behaviour of profiles,
portfolio and project installation. The rule: a finding without a test comes back.

## Calibrated on live sites, not fixtures

Thresholds are not guesses. They were checked against six production sites —
7,149 sitemap URLs, 5,041 pages fetched and parsed — and the run changed the
tool in three ways:

* **One cause, not four findings.** Two of the six sites served every page as an
  empty JavaScript shell. The tool reported 1,099 `js-shell` *and* 1,099
  `low-uniqueness` *and* 1,098 `orphan` — one disease counted four times. Checks
  that need text or links are now skipped on a shell, and the run says how many
  shells there were.
* **Duplicates are groups, not pages.** 588 near-duplicate pages turned out to be
  72 groups, the largest holding 24. "Rewrite 588 pages" is a sentence;
  "untangle 72 topics" is a task.
* **A finding on every page is a template property.** `vague-anchor` fired on
  2,970 of 2,970 pages — the culprits were a language switcher (`中文`) and a
  social link (`VK`), short in characters and perfectly informative. Anchor
  length is now measured in the right unit, and any code that hits ≥90% of pages
  is labelled as something to fix once in the template.

---

## For agents

`SKILL.md` at the root is the overview. `indexgap/skills/` holds four
stage-specific skills — `indexgap-plan`, `indexgap-review`, `indexgap-publish`,
`indexgap-portfolio` — which `indexgap init` copies into your project's
`.claude/skills/`. A narrow skill fires more accurately than a broad one:
the agent sees only the commands and finding codes for the stage it's in.

Codex users: `indexgap init --agents` writes a marked block into `AGENTS.md`.

---

MIT.
