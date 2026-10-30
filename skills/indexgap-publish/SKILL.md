---
name: indexgap-publish
description: >
  Ship and diagnose a programmatic site from local files: a sitemap with
  sharding and an honest lastmod, IndexNow for changed pages only (Bing,
  Yandex, Seznam, Naver — not Google), and the generated → sitemap → indexed
  funnel from Search Console, Bing, Yandex Webmaster, Ahrefs or GA4 exports.
  Use when `indexgap check` is clean, before and after deploy, and when asked
  why pages are not indexed or get no traffic. Triggers: make a sitemap,
  ping Bing or Yandex, submit to IndexNow, submit my pages to Google, why
  are my pages not indexed, "crawled - currently not indexed", traffic
  dropped on my city pages, Search Console or Webmaster export.
---

# Publishing, and where the pages went

## Before the first command

1. `indexgap init` in the project root writes `indexgap.json`; after that the commands need no paths or flags.
2. Show the person what `init` guessed: pages directory, site address, profile, dataset. Ask them to confirm.
3. The pages directory is the one the site serves as `/`; sitemap and IndexNow addresses are built from it.
4. Each domain has its own IndexNow key: `indexgap init --key` mints a new one; someone else's gives a 403.
5. No `indexgap` command: `pipx install indexgap`; from a checkout, `pipx install -e <path>` or `PYTHONPATH=<path> python3 -m indexgap`.

## Order

1. `indexgap check --strict` passes — or the person has accepted each remaining critical finding.
2. Build, then `indexgap sitemap`: the generator may have wiped `sitemap.xml` along with its output directory.
   With a copy of what is in production, `indexgap diff ./prod-build ./out --strict` lists pages
   that disappear or close and template changes. Show anything critical to the person before deploying.
3. Deploy. Confirm that `https://site/<key>.txt` and one changed page are live.
4. `indexgap notify` as a dry run → show the person → `--send` once they explicitly agree.

`notify` marks addresses as sent from the hash of the local text. Sent before
the deploy, the engine crawls the old version and the change is never sent
again. The queue fills up even while critical findings are open: `notify` only
warns when `indexgap-check.json` in the current directory has them on the pages
being sent.

## Sitemap

```bash
indexgap sitemap ./out --site https://example.com --out-dir ./out
```

Sharding past 45,000 URLs happens on its own. `lastmod` changes only when the
text changed: if it equals the build date on every page at once, the engine
stops believing it. The hash is computed from the main text, the title and the
description — editing one menu item does not mark the whole site as modified.

If `--out-dir` is a subfolder rather than the publish root, add
`--public-prefix` with the path the files will be served under: otherwise the
shard index points at the root while the files sit elsewhere.

Drafts (`status: draft` in the frontmatter) never reach the sitemap — the
command reports how many there were. Foreign `sitemap-news.xml` and
`sitemap-images.xml` in the publish directory are left alone.

**The manifest.** State — lastmod, the submission queue, the list of sitemap
files this tool created — lives in `.indexgap-manifest.json` next to
`indexgap.json`; without `indexgap.json` it goes next to the pages, so run
`init` first (or pass `--manifest`). **Commit it**: without it every CI build
treats all pages as new. It must not end up in the published directory: an old
manifest beside the pages is still picked up — move it next to `indexgap.json`.

## IndexNow

```bash
indexgap notify ./out --site https://example.com --key <your-key>
```

The key: 8–128 latin characters, digits and hyphens (a uuid without braces
works). It also becomes the file `<key>.txt` at the **site root**:

```bash
indexgap notify ./out --site https://example.com --key <your-key> \
    --write-key --key-dir ./out
```

`--key-dir` is the publish directory, not the source directory: a key file next
to markdown never reaches the site, and the protocol answers 403. If the file is
not at the root, `--key-location` gives its address.

**If the build wipes the publish directory**, anything put there by hand is gone
after the next build. Keep the key file in the generator's static assets
(`static/`, `public/` — whatever is copied into every build), and run
`indexgap sitemap` after every build.

A dry run by default: nothing goes to IndexNow, and the command prints how many
addresses are new, changed, unchanged and gone, and the first 20 addresses in
the queue. Submit with `--send` only after
the person explicitly agrees. Only what changed is sent: every URL spends the
site's crawl budget. A page that is gone, if it was ever published, gets a 301
to the nearest live page.

Without a manifest `--send` refuses: it would submit the whole site. If this
really is the first submission, add `--first`. If the manifest was lost (a clean
build in CI), restore it rather than resubmitting the site on every deploy.

If some batches are not accepted, the accepted ones are still marked and will
not be sent again; the rest stay in the queue.

The dry run does not touch the network. With `--send` the protocol's participant
registry is downloaded; `--offline` does without it — the cache or the built-in
list is used. The cache lives in the user's home directory, not next to the
pages.

**Always say out loud who IndexNow does NOT cover.** The command prints the
participants (bing, yandex, seznam, naver, yep and others) and, separately, who
is missing. Google does not take part: for Google there are the sitemap, the
`Sitemap:` line in robots.txt and Search Console. Someone who does not know this
will wait for an effect in Google that never comes.

robots.txt also has to sit in the publish root; if that directory is generated,
the generator emits it.

## When there is no traffic

```bash
indexgap doctor ./out --site https://example.com \
    --sitemap ./out/sitemap.xml \
    --indexed gsc.csv --indexed bing.csv --indexed yandex.csv
```

It builds the funnel and explains every loss addressably. A page can land in
several causes at once — both fixes are needed. Only pairs above the duplicate
threshold count as "near-duplicates": no canonical between `similar` pages. The
report is `indexgap-doctor.html`; content checks do not run here — `indexgap
check` does those.

### About exports

Search Console has two different "Pages":

* **Indexing → Pages** → *View data about indexed pages* → Export — a real
  index list (up to 1,000 rows). Ask for this one.
* **Performance → Pages** → Export — an impressions report. An indexed page with
  no impressions is not in it: absence there is not "not indexed". On a young
  site this systematically overstates losses — tell the person.

Panels differ in format; encoding and delimiter are detected, and cp1251 with
semicolons reads fine. If the tool is unsure whose export it is, it asks for a
label: `--indexed yandex=export.csv`. Two exports under one label merge into one
index, and the comparison between engines disappears.

### If there is no webmaster panel

Ahrefs, Semrush, Screaming Frog, Sitebulb, GA4, Matomo or a plain list of
addresses are read: CSV with any delimiter and encoding, XLSX, JSON, NDJSON, an
XML sitemap, one address per line.

```bash
indexgap doctor ./out --site https://example.com \
    --indexed ahrefs=top-pages.xlsx --indexed ga4=pages.csv
```

**These are different claims, and confusing them is not allowed.** A webmaster
panel answers "does the engine know this page" directly. Analytics proves
indexation only for pages someone visited — its silence proves nothing. A
crawler proves a crawl, not indexation. Ahrefs and Semrush are *their* index,
not Google's. The tool keeps that separation itself: the funnel step is renamed
along with the source. If they have Search Console, ask for it — the rest
supplements it; if not, work with what there is, but do not call the result
indexation.

**Ask for exports from every panel where the site is verified, not just
Google.** When the exports are index lists, this changes the diagnosis:

* the page is missing **everywhere** — a technical problem, fixed through the
  "why pages are not indexed" section;
* the page is missing **from one engine only** — the others accepted it, so it
  is reachable and valid. The issue is that engine's quality judgement or
  indexing speed, and technical fixes rarely help.

With impressions exports (Performance, analytics) this conclusion is not drawn:
absence there means "no impressions yet". Bing and Yandex usually index faster
than Google — a discrepancy in the first weeks often just means "not yet".

Name the "no cause could be established locally" category honestly: often not
enough time has passed since publication. And show them where to look
themselves — Search Console and the other panels. If the report says one thing
and Search Console says another, Search Console is right.
