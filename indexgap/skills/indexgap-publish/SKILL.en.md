---
name: indexgap-publish
description: >
  Publishing a programmatic pipeline: a sitemap with sharding and an honest
  lastmod, IndexNow for the pages that actually changed, and the
  generated → sitemap → index funnel for working out where traffic is lost.
  Use after reviewing pages, and when someone asks why pages are not indexed.
---

# Publishing, and where the pages went

## Sitemap

```bash
indexgap sitemap ./content --site https://example.com --out-dir ./public
```

Sharding past 45,000 URLs happens on its own. `lastmod` changes only when the
text changed: if it equals the build date on every page at once, the engine
stops believing it. The hash is computed from the main text, the title and the
description — editing one menu item does not mark the whole site as modified.

If `--out-dir` is a subfolder rather than the publish root, add
`--public-prefix` with the path the files will be served under: otherwise the
shard index points at the root while the files sit elsewhere.

Drafts (`status: draft` in the frontmatter) never reach the sitemap — the
command reports how many there were. That is no reason to skip `check` before
publishing, but it closes one classic mistake.

State lives in `.indexgap-manifest.json` next to the pages: lastmod, the
submission queue, and the list of sitemap files this tool created. Add it to
your static generator's `.gitignore` so it does not ship in the build. Foreign
`sitemap-news.xml` and `sitemap-images.xml` in the publish directory are left
alone.

## IndexNow

```bash
indexgap notify ./content --site https://example.com --key <your-key>
```

The person invents the key themselves: 8–128 latin characters, digits and
hyphens (a uuid without braces works). It also becomes a file at the **site
root**:

```bash
indexgap notify ./content --site https://example.com --key <your-key> \
    --write-key --key-dir ./public
```

`--key-dir` is the publish directory, not the source directory. A key file
placed next to markdown never reaches the site, and the protocol answers 403.

A dry run by default. Show the person how many URLs will go and which ones, and
submit only after they explicitly agree, with `--send`. Only what changed is
sent: every URL spends the site's crawl budget.

If some batches are not accepted, the accepted ones are still marked and will
not be sent again; the rest stay in the queue.

**Always say out loud who IndexNow does NOT cover.** The command prints the
participants from the protocol registry (bing, yandex, seznam, naver, yep and
others) and, separately, who is missing from it. Google does not take part: for
Google there are only the sitemap and Search Console. Someone who does not know
this will wait for an effect in Google that never comes.

In CI without network access use `--offline`; the cache or the built-in list is
used. The registry cache lives in the user's home directory, not next to the
pages.

## When there is no traffic

The package's main command:

```bash
indexgap doctor ./content --site https://example.com \
    --sitemap ./public/sitemap.xml \
    --indexed gsc.csv --indexed bing.csv --indexed yandex.csv
```

It builds the funnel and explains every loss addressably. A page can land in
several causes at once — that happens, and both fixes are needed.

Only pairs above the duplicate threshold count as "near-duplicates". Pages
marked `similar` do not go there: you must not set a canonical between them.

The report is written to `indexgap-doctor.html`. Content checks do not run here
— `indexgap check` does those.

### About exports

The Search Console "Pages" export is an **impressions report**, not an index
report: a page that is indexed but had no impressions will not appear in it. On
a young site this systematically overstates losses, and the person needs to be
told, or they will rush to fix what already works.

Panels differ in format; encoding and delimiter are detected, and cp1251 with
semicolons reads fine. If the tool cannot identify an export with confidence it
says so and asks for a label: `--indexed yandex=export.csv`. Do not let that
slide: two exports under one label merge into one index, and the comparison
between engines disappears.

### If there is no webmaster panel

Not everyone has Search Console, but nearly everyone has Ahrefs, Semrush,
Screaming Frog, Sitebulb, GA4, Matomo — or just a list of addresses. All of it
is read: CSV with any delimiter and encoding, XLSX without re-saving, JSON,
NDJSON, an XML sitemap, a list of addresses one per line.

```bash
indexgap doctor ./content --site https://example.com \
    --indexed ahrefs=top-pages.xlsx \
    --indexed screamingfrog=internal_html.csv \
    --indexed ga4=pages.csv
```

**But these are different claims, and confusing them is not allowed.** A
webmaster panel answers "does the engine know this page" directly. Analytics
proves a page is indexed, but only for pages someone actually visited — its
silence proves nothing. A crawler proves a crawl, not indexation. Ahrefs and
Semrush are *their* index, not Google's.

The tool keeps that separation itself: the funnel step is renamed along with the
source, and when a crawler export sits next to a panel it says plainly that the
step's number is higher than real indexation. The "present in one, absent from
another" comparison runs between panels only.

What to tell the person: if they have Search Console, ask for it — everything
else supplements it. If they do not, work with what there is, but do not call
the result indexation.

**Ask for exports from every panel where the site is verified, not just
Google.** This changes the diagnosis rather than refining it:

* the page is missing **everywhere** — a technical problem, fixed through the
  "why pages are not indexed" section;
* the page is missing **from one engine only** — the others crawled and accepted
  it, so it is reachable and valid. The issue is that engine's quality judgement
  or its indexing speed, and technical fixes rarely help.

Without the split both situations look identical and the person fixes the wrong
thing. Bing and Yandex usually index faster than Google — a discrepancy in the
first weeks often just means "not yet", not a problem.

Name the "no cause could be established locally" category honestly: often it
simply means not enough time has passed since publication.

And show them where to look themselves — Search Console and the other panels.
If the report says one thing and Search Console says another, Search Console is
right.
