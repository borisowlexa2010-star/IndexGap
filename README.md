# indexgap

[![tests](https://img.shields.io/github/actions/workflow/status/borisowlexa2010-star/IndexGap/tests.yml?branch=main&label=tests)](https://github.com/borisowlexa2010-star/IndexGap/actions/workflows/tests.yml)
[![pypi](https://img.shields.io/pypi/v/indexgap)](https://pypi.org/project/indexgap/)
[![python](https://img.shields.io/pypi/pyversions/indexgap)](https://pypi.org/project/indexgap/)
[![dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)](https://github.com/borisowlexa2010-star/IndexGap/blob/main/pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-green)](https://github.com/borisowlexa2010-star/IndexGap/blob/main/LICENSE)

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
pipx install indexgap
```

`pipx` keeps the tool in its own environment and still puts `indexgap` on your
PATH — `pip install` into a system Python is refused outright on most current
distributions. If you do not have it: `python3 -m pip install --user pipx`.
To work from the `main` branch instead: `git clone` the repository and
`pipx install -e .` in it (or run it without installing:
`PYTHONPATH=/path/to/IndexGap python3 -m indexgap`).

**See it work before pointing it at your own site.** The repository carries a
ten-page demo with one of each common failure planted in it:

```bash
git clone https://github.com/borisowlexa2010-star/IndexGap && cd IndexGap/examples/demo-site
indexgap check . --site https://demo.example \
  --dataset cities.csv --sitemap sitemap.xml --robots robots.txt
```

It reports a price that is not in the data (`$1,900` where the row says
`$1,600`), two pages that are 89% the same text, a page no link leads to, a
page closed with `noindex`, a thin page, an AI search crawler blocked in
robots.txt — and a funnel of 10 generated, 9 indexable, 7 in the sitemap.

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
indexgap diff ./prod ./out          # two builds before a deploy: what this deploy breaks
indexgap brief --write              # turn the findings into work orders in indexgap-briefs/
indexgap sitemap --out-dir ./public # sitemap with sharding and an honest lastmod
indexgap notify --key <your-key>    # tell IndexNow what actually changed
indexgap doctor --sitemap ./public/sitemap.xml --indexed gsc.csv
indexgap portfolio projects.json    # every site you own, in one run
indexgap profiles                   # what the content-type presets change
indexgap cite --domain example.com --prompt "best visa service for Singapore"
                                    # do AI answers cite you? (your own API keys)
indexgap fetch https://example.com --out-dir ./live
                                    # no build? download the live site for check
```

### No build? Fetch the live site

`check` reads files. When all you have is a URL — a client's site, a
competitor, a CMS you cannot build locally — `fetch` downloads the pages listed
in the sitemap into a directory that `check` reads as if it were the build:

```bash
indexgap fetch https://example.com --out-dir ./live        # 500 pages by default
indexgap check ./live --site https://example.com/ --sitemap live/sitemap.xml
```

The sitemap comes from `--sitemap`, else the `Sitemap:` lines of robots.txt,
else `/sitemap.xml`. robots.txt is obeyed for the `indexgap` user agent (a
5xx on robots.txt stops the crawl, as it stops Googlebot); no request ever goes
to another host, redirects included; `--limit` caps the pages (`--limit 0`
means every page and only works with `--all`); `--delay` and `--jobs` keep it
polite. `/a/b/` is saved as `a/b/index.html`, `/a/b` as `a/b.html`, and
`fetch.json` records each page's URL, status, redirects, size and type, so
`check` reports every page under the exact URL it came from. `X-Robots-Tag`
headers land in `_headers`, which `check` already reads; robots.txt and the
sitemap files are saved next to the pages. Pages over 2 MB (where Googlebot
stops reading) are flagged; 4xx/5xx and non-HTML responses are recorded but not
saved. The summary prints the exact `check` command to run next.

```bash
indexgap fetch https://example.com --out-dir ./live --crawl    # follow links too
indexgap fetch https://example.com --out-dir ./live --render   # save what Chrome renders
```

`--crawl` also follows links, breadth first: the home page and the sitemap
URLs come first, then the links they contain, then the links of those, under
the same `--limit`, `--delay`, `--jobs` and robots.txt rules. Only links to the
same host are followed (`www.` counts as the same host), never links with a
query string (unless the URL is in the sitemap) and never links to images,
PDFs, scripts and other files. `fetch.json` records `found_by` (`sitemap` or
`link`, plus `linked_from` for a link) for every URL, and the summary lists the
pages found only by links (they are missing from the sitemap), the sitemap URLs
no fetched page links to (orphan candidates; an estimate when `--limit` cut the
crawl short) and the links that answer 4xx/5xx. With `--crawl` a missing
sitemap is not an error: the crawl starts from the home page alone.

Without `--render`, pages whose HTML is an empty JavaScript shell are counted
and the summary says so. `--render` runs an installed Chromium-family browser
(`google-chrome`, `chromium`, `chromium-browser`, `chrome` or `msedge` on PATH,
or Chrome/Chromium in `/Applications` on macOS; `--browser PATH` to pick one)
as `--headless=new --dump-dom --virtual-time-budget=5000` on each saved page
and saves the rendered DOM instead of the raw HTML; status, size and headers
in `fetch.json` stay those of the raw response, and the page gets
`rendered: true`. Each page gets a fresh throwaway profile and 60 seconds; a
browser that hangs is killed and the raw HTML is kept. Without a browser
`--render` stops before the first request (exit 2) and says what to install.
The browser is let out only to the site: all its traffic, loopback included,
goes through a proxy the package runs, which connects only to the site's host
and port at the address resolved once. Scripts, fonts or APIs from other hosts,
other ports on your machine and the cloud metadata address do not load (a page
that needs them renders without them). The sandbox stays on; as root on Linux
`--render` refuses to start unless `--browser-no-sandbox` says you accept the
risk. What `fetch` still
cannot see: URLs with query strings that are not in the sitemap, and, without
`--crawl`, pages that are not in the sitemap.

`sitemap` and `notify` keep their state in `.indexgap-manifest.json`, next to
`indexgap.json`: when each page last changed and what has been submitted.
**Commit it.** Without it a clean CI checkout sees every page as new — today's
`lastmod` everywhere — and `notify --send` refuses to submit the whole site
unless you say `--first`. On the 5,546-page Apache APISIX build a full `check`
takes about 30 seconds and under 600 MB of memory (Apple M1 Max); on a generated
50,000-page site, about 2.5 minutes and 5 GB. Pages are parsed in parallel —
up to eight processes, `INDEXGAP_JOBS=1` for one.

Output is English by default, Russian with `--lang ru` (or `INDEXGAP_LANG`, or
your system locale). That includes the HTML report, every finding description,
`--help`, and the skills `indexgap init` installs into your project.

Understands both built HTML and Markdown sources with frontmatter. Input file
encoding is detected, not assumed: UTF-16, BOM, and the cp1251 CSVs that
Russian Excel produces all read correctly. Exports are read as they come —
CSV with any delimiter, XLSX straight from Ahrefs or Semrush without
re-saving, JSON, NDJSON, an XML sitemap, or a plain list of URLs — and the
keyword column is found whether the export calls it `Keyword`, `Фраза`,
`Запрос` or `Search Term`.

## In CI

A site that already has a hundred critical findings cannot turn on `--strict`:
the build is red from day one, and someone switches the check off. A baseline
fixes that. Run once, commit the data, and from then on the build fails only
on findings that are new:

```bash
indexgap check --out indexgap-baseline.json      # once; commit the file
indexgap check --baseline indexgap-baseline.json --strict
```

A finding is matched by page, check and level, not by its wording, so a
changed number in the message does not make it new. Findings with a subject —
which bot is blocked, where a broken link points, which page is the twin — also
compare the subject: unblocking one AI crawler and blocking another is a new
finding, while fewer broken links is not. The run prints what appeared and what
is gone, and both go into the JSON under `baseline`.

Some findings are accepted on purpose: a print version without a viewport, a
glossary that is meant to be short. List them in `indexgap.json` and they stop
counting toward the score, the briefs and `--strict`; the run prints how many
were accepted, and the JSON keeps them under `accepted`:

```json
{"ignore": {"no-viewport": ["/print/*"], "thin": ["/glossary/*"], "no-og": true}}
```

A code that does not exist is an error, not a silent no-op.

### Before a deploy: `diff`

Each build can look fine on its own while the deploy between them breaks the
site: a page that had impressions is simply not generated any more, one line in
a template puts `noindex` on a whole section. `diff` compares the build that is
in production with the new one:

```bash
indexgap diff ./prod-build ./out --site https://example.com --strict
```

It reports pages that disappear (critical if they were indexable and nothing
redirects them — `_redirects`, `netlify.toml` and `vercel.json` next to the new
build are read, splats and `:params` included), pages that close (noindex
appears, the canonical starts pointing elsewhere, a draft, a redirect stub),
title/H1/description changed on most pages of one URL template at once, pages
whose text drops by more than half, new pages per template, and — unless
`--no-checks` — critical `check` findings that are new in NEW against OLD.
Numbers that are not in the data are findings only against a dataset: pass
`--dataset keywords.csv` (and `--keyword` if the column is named otherwise),
or name it in `indexgap.json`, and both builds are checked against it.
The report goes to `indexgap-diff.html` with the data in `indexgap-diff.json`
(`items` in the same level/url/code/message shape as findings); `--strict`
exits `1` if anything is critical.

### Risk by template

`check` also groups pages by URL template (`/plumbing/*/`, templates of at
least ten pages; the rest is `other`) and scores each 0–100: the average over
its pages of the page's worst finding, where a critical finding weighs 0.5–1
by its code and a warning 0.15–0.3. The five riskiest are printed after the
summary, the report has a table, and the JSON has `templates` with `pattern`,
`pages`, `critical_share`, `warning_share`, `top_codes` and `risk`. A site with
no template of ten pages gets an empty list and nothing extra in the console.

Exit codes: `0` — the run finished (findings or not); `1` — `--strict` and there
are critical findings (only new ones, with `--baseline`); `2` — the input is
wrong: a directory or a file that is not there (a typo in `--sitemap` or
`--robots` included), a site address without a scheme, a foreign file where a
report would be written, or a portfolio where no project could be checked;
`130` — interrupted. The JSON carries `"schema": 2`; it changes only when the
meaning of a field does. Steps of the funnel and cross-engine rows have stable
`id`s — the `name` beside them is translated. For machines, run with `--lang en`.

On GitHub it is one step. The summary — counts, new critical findings, the most
frequent checks — appears on the run page, and the HTML report is kept as an
artifact:

```yaml
- run: npm run build
- uses: borisowlexa2010-star/IndexGap@v1.18.1
  with:
    root: out
    site: https://example.com
    baseline: indexgap-baseline.json   # optional
    args: --sitemap out/sitemap.xml    # optional, anything `check` accepts
```

With `old-root` the same step also runs `diff` against the previous build:
its summary goes on the run page after the check's, its report and data into
the same artifact (outputs `diff-report`, `diff-data`), and with `strict` the
step fails if either run fails. The action does not fetch the previous build —
that depends on how you deploy. The simplest source is the previous commit:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 2                     # the previous commit as well
- run: npm ci && npm run build         # the new build → out/
- name: Build the previous commit into old/
  run: |
    git worktree add ../prev HEAD~1
    (cd ../prev && npm ci && npm run build)
    mv ../prev/out old
- uses: borisowlexa2010-star/IndexGap@v1.18.1
  with:
    root: out
    site: https://example.com
    baseline: indexgap-baseline.json
    old-root: old
    diff-args: --dataset keywords.csv  # optional, anything `diff` accepts
```

`HEAD~1` is what is in production only if every commit to the branch is
deployed; on a pull request it is the tip of the base branch. If production is
something else, download the last deploy's build instead (for example
`actions/download-artifact` with `run-id` and `github-token`) and pass its
directory as `old-root`. `old-root` needs `root`: the directory of the new
build has to be named.

---

## What it checks

**Before generating** — exact duplicate keys, slug collisions and *same-intent*
keys. That last one matters most: two keywords meaning the same thing will
produce two competing pages, and it is cheaper never to create the second.
Each key is also labelled by intent — buying, choosing, learning — so the pages
that bring customers can be generated first.

**After generating — the text**

| Check | Why it matters |
|---|---|
| **Numbers absent from your data** | prices, terms and counts are verified against the source row. A price, or a number with one of your project's units, that is not in the data is a critical finding; a number with any other word ("12 years", "3,500 orders") is listed for you to check by eye. Neither is forgiven for being repeated on many pages |
| Identical heading skeletons | different words, same structure — a stamping tell |
| Identical opening sentences | the second tell |
| Unfilled template slots | `{{city}}`, `%CITY%`, `undefined`, `NaN`, `Plumbers in , TX`, lorem ipsum, a model's "Certainly! Here is…" left in the text |
| JSON-LD that disagrees with the page | a price, rating or review count in the markup that the visible text does not show |
| A past year in the title | "Best plumbers 2024" in 2026: the template nobody updated |
| Leftover brief, `status: draft` | unfinished pages never reach the sitemap or the IndexNow queue |
| "Click here" anchors | a link with no meaning in it |

**After generating — the structure**

Near-duplicates (exact pairwise below 400 pages, MinHash + LSH above), share of
unique text measured *by bigrams* rather than words, thin pages, orphans,
broken internal links, section pages that do not link to their own pages, click
depth, `noindex` (also from `_headers`, `netlify.toml`, `vercel.json`),
`nosnippet`, foreign canonicals, pages robots.txt does not let Googlebot crawl,
missing or duplicate H1, a title and an H1 that share no word, duplicate titles
and descriptions, missing viewport, missing og:title / og:image, HTML over the
2 MB Googlebot reads, images over 1 MB.

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

## From findings to work orders

A report answers "what is wrong with me". `indexgap brief` answers "what do I
do" — it lays the same findings out as markdown files in `indexgap-briefs/`,
mirroring the page tree, each with an imperative fix, the thresholds the fix has
to meet, the dataset row as the only permitted source of numbers, and the exact
command that checks the fix. For built pages the brief says so: the fix goes into
the template, the data or the generator, then the site is rebuilt.

```bash
indexgap brief --dataset keywords.csv        # dry run: says what it would write
indexgap brief --dataset keywords.csv --write
```

On the live 2,970-page catalogue the check reports 6,074 findings and `brief`
writes 966 work orders. The difference is three placement rules, and they are
the whole point:

* **A property of the template gets one brief, not 2,919.** `no-question-headings`
  fired on 2,919 of 2,970 pages. That is one edit to one template, and 2,919
  identical tasks would bury the 51 pages that actually differ. The same holds
  per language: a finding on every page of the Chinese version is 10% of the
  site but still one template fix. And per URL pattern: 170 pages of
  `/plumbing/*/` next to 30 blog posts — a defect of the city template is 85%
  of the site and 100% of its template, so it is one brief for that template,
  while a blog post with the same finding keeps its own.
* **Near-duplicates are fixed as a group.** 588 duplicate findings are 72
  groups. One page out of a group of 17 cannot be fixed alone — the brief goes
  to the group. Pages built for different queries (a city, a model) need their
  own data, not a canonical that would hide them; pages for one query are merged
  into one.
* **robots.txt, markup and hreflang clusters belong to the site**, not to a
  page, and live in their own file.

`--limit` (50 by default) writes the heaviest pages first; 892 briefs is not a
task list, it is a second report. Nothing is created without `--write`.

**The package writes no text, on purpose.** Its central check compares the
numbers on a page against the dataset row that produced it. If the package
supplied those numbers itself, the check would be checking its own output and
would always be green. So `brief` states the task and stops; a person or an
agent writes the words.

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

**AI citations are a step of their own.** Bing Webmaster Tools → AI Performance
exports the pages Microsoft Copilot cited and how often. Pass it like any other
export (`--indexed ai-performance-pages.csv`; the `Citations` column is enough
for the tool to recognise it) and the funnel gains a last step — *cited* — after
the index. It is deliberately not merged into the index step: the export is a
sample, 93 pages on a site with over a thousand indexed, and merged in it would
declare everything else unindexed. What it adds that nothing else can: pages
the AI still cites although you closed them from search, and cited pages you
left out of the sitemap. The queries export from the same screen holds no page
addresses; the tool says so and tells you which tab to export instead.

**Every sitemap, and everything the engine knows that you did not generate.**
`--sitemap` can be repeated, and when robots.txt declares sitemap files you did
not pass, the tool names them — on a live site one `sitemap.xml` held 13 URLs
and the three declared files together held 94. Addresses the engine reports but
the site does not contain are listed by meaning: other hosts (staging, admin,
internal tools — the ones to close), pages that no longer exist (redirect them),
and files.

One honest caveat the tool states out loud: the Search Console "Pages" export
is an *impressions* report, not an index report. A page that is indexed but has
no impressions won't appear in it. When that export is the only panel, the step
is called "with impressions in search" rather than "in the index", and pages
without impressions are not reported as unindexed.

**`doctor --live` separates what is done from what is left.** An export shows
the past: on one live site four of five "missing" pages already answered 301,
and on another six of seven stray hosts were already closed with `noindex`.
With `--live` each such address is checked over the network — a page is fine
if it redirects or answers 404/410, a host if it sends `noindex`, sits behind a
login or has moved to another host — and only what still needs a hand is
listed. Redirects within a host are followed to the final answer: a GitLab root
that 302s to a public sign-in page is open, not closed. It is the one part of
`doctor` that uses the network, so it runs only when asked.

---

## Multilingual and multi-region

A programmatic pipeline is usually multilingual, and that breaks in ways a
single-language site never does.

Text volume and title/description length are measured by each page's **script**,
in display width — not by one language detected for the whole project. That
distinction is not academic: on a live 2,970-page catalogue in ten languages the
project language came out as `en`, every Chinese page was counted as English,
and all 174 `thin` findings were false. Width also handles mixed strings, which
is what real pages are: those Chinese titles are 43% Han and the rest Latin.

Anchor length is judged only in scripts where length means something. All 914
`vague-anchor` findings on that same site were false — "यमन" (Yemen) and "হোম"
(Home) are three characters and complete words.

**hreflang** is checked as a cluster: a missing self-reference, a one-way link
(Google discards the whole cluster rather than counting it partly), an alternate
that is noindex or canonicalised elsewhere, a canonical that leaves the language
and cancels the cluster, a missing `x-default`, and language codes where a
country code was meant — `uk` is Ukrainian, not the United Kingdom. On a
monolingual site none of this runs.

And `en-us` versus `en-gb` is **not** a duplicate. Those pages are legitimately
near-identical; "keep one and set a canonical" would delete the regional
version. Pairs inside one hreflang cluster are excluded from the duplicate
check and reported separately.

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

`indexgap cite` measures the thermometer, and says so: it asks Perplexity, the
OpenAI Responses API, the Gemini API and Grok a set of real questions and counts
how often your domain comes back in the sources. It reports a share of runs, not
yes/no, because these answers are not deterministic. And it never says "ChatGPT
cites you" — what it measured is the API, which OpenAI's own docs describe as
behaving differently from the product. It is the only command that needs API
keys, it is off by default, and it sends nothing without `--send`.

Where an engine publishes what it actually cited, the thermometer is not needed.
Bing Webmaster Tools does, for Copilot, and `indexgap doctor` reads that export
directly — observed citations per page, no keys, no sampling of your own. It
still says what the number is not: a count of citations, not a ranking, and
silence in it proves nothing about indexing.

No `llms.txt` generator either. Google has stated it does not support it and
has no plans to; no engine has confirmed using it for ranking. Generating a
file nobody reads is a ritual, not a feature.

It also doesn't write or rewrite content, check rankings, or call paid services.
`indexgap brief` formulates the task and stops there — on purpose. The central
check compares the numbers on a page against the dataset row that produced it;
if the package supplied those numbers itself, the check would be checking its
own output and would always be green.
Rejecting keywords and acting on contested findings is always confirmed by a human.

And it does not replace Search Console — it leads you there. If the tool says
one thing and Search Console says another, Search Console is right.

---

## Tests

```bash
python3 -m unittest discover -s tests
```

941 scenarios. Each one is a reproduced defect: from four waves of adversarial
review (the latest by eight reviewers at once — new generators, a seeded
catalogue measuring what is missed, messy input, scale, the truth of these
docs, an agent following the skills, the competition), from runs against live
sites, plus 160 tests written to kill the mutants the suite let live. The rule:
a finding without a test comes back.

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

**And on other people's sites.** The built sites of twelve open projects were
then run through it — mdBook and `just` (mdBook), MkDocs and HTTPX (MkDocs),
Zola, Jekyll, Immer (Docusaurus), Gin (Astro Starlight), NetworkX (Sphinx),
isort, pre-commit, Google's style guides (GitHub Pages sources): 4,000 pages on
eight generators. Not one crash, and five kinds of false alarm, each of which
would repeat on every site built the same way: language versions joined only
by hreflang called unreachable (1,122 pages on one site), a heading-only page
called a JavaScript shell, template partials taken for pages, Markdown without
front matter dropped from a GitHub Pages source, content findings on `noindex`
service pages. Critical findings across the twelve went from 1,606 to 397, and
the ones that remain were checked by hand.

**And on twelve more.** Hugo (relearn), Docusaurus with i18n (Apache APISIX),
VitePress (Element Plus), Hexo, Pelican (pyvideo.org, 47,000 pages), Gatsby,
Nuxt, Eleventy, pkgdown (dplyr), Docsify and Next.js. Six causes made about
15,000 findings — Hugo's print copies judged as pages, a closed section of old
docs versions reported 8,000 times, `index.source.md` taken for pages, flat
`name.html` pages given a `/name/` address that 404s, one malformed link that
killed a 47,000-page run. Across eleven of them critical findings went from
14,699 to 2,720.

---

## For agents

`SKILL.en.md` at the root is the overview (`SKILL.md` is the same in Russian). `indexgap/skills/` holds four
stage-specific skills — `indexgap-plan`, `indexgap-review`, `indexgap-publish`,
`indexgap-portfolio` — which `indexgap init` copies into your project's
`.claude/skills/`. A narrow skill fires more accurately than a broad one:
the agent sees only the commands and finding codes for the stage it's in.

Codex users: `indexgap init --agents` writes a marked block into `AGENTS.md`.

---

MIT.
