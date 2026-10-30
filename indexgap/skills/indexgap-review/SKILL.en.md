---
name: indexgap-review
description: >
  Pre-publish QA for many pages generated from a dataset (programmatic SEO):
  numbers absent from the data, unfilled template slots ({{city}}, undefined,
  NaN), near-duplicates, template stamping, orphans, broken internal links,
  thin pages, robots.txt, hreflang, readability for AI search. Then repair
  briefs (`indexgap brief`): fix in the template, dataset or generator,
  rebuild, re-check. Use after generating pages and when asked to fix what
  the check found. Triggers: review or QA generated pages, invented facts,
  duplicate city pages, unfilled placeholders, apply the repair briefs, fix
  what indexgap found. Not for a single hand-written page or for site speed.
---

# The pre-publish review

## Where to make the fix

If the pages are produced by a script, a static-site generator or a CMS
export, every fix goes into the template, the dataset or the generator — never
into the built files. The next build overwrites them, and `check` stays green
only until then. Find the build command first (ask if unsure). The loop is:
edit the source → rebuild → `indexgap check`.

A brief's `File:` line names the built file, so you can see which template
and which dataset row produced the page. It is not the file to edit. Edit pages
directly only when they are the source themselves: Markdown written from
`indexgap plan` stubs.

## Before the first command

1. `indexgap init` in the project root writes `indexgap.json`; after that plain `indexgap check` is enough.
2. Show the person what `init` guessed: pages directory, site address, profile, dataset. Ask them to confirm.
3. The pages directory is the one the site serves as `/`. Getting it wrong produces "every page is an orphan".
4. The profile (`catalog`, `events`, `ugc`, `product`) changes thresholds and switches checks off — the person confirms it too.
5. No `indexgap` command: `pipx install indexgap`; from a checkout, `pipx install -e <path>` or `PYTHONPATH=<path> python3 -m indexgap`.

## Running it

```bash
indexgap check ./out --site https://example.com --dataset keywords.csv
```

`--site` is the full site address including the scheme. It also determines the
home page (a different one goes in `--home`); if the home page is not among the
files, click depth is not computed. `--dataset` switches on fact-checking:
without it there is nothing to verify numbers against.

The report is written to `indexgap-check.html` and `indexgap-check.json`.
`--out report.json` writes the data to `report.json` and the HTML beside it, to
`report.html`. `doctor` writes to its own files and never overwrites this one.

No build, only a URL — a client's site under audit, a CMS you cannot build
locally: run `indexgap fetch https://example.com --out-dir ./live` first, then
the `check` command that `fetch` prints at the end. It downloads the pages in
the sitemap (500 at most by default, obeying robots.txt and never leaving the
host) and keeps the status codes, redirects and `X-Robots-Tag` headers. Fixes
from such a report belong to the site owner, in the source; never edit the
downloaded files. When a build exists, check the build: `fetch` cannot see text
that JavaScript renders.

## What to look at first

Start with `unsupported-number` and `unfilled-slot`, wherever they stand in the
output: the command prints its top three causes by count, not by importance.

If the summary is followed by "Riskiest templates", start the fix with the top
one: risk 0–100 is the average severity of the worst finding over the pages of
a URL template (`/plumbing/*/`), and one template fix clears it from all of
them. The same table is in the report; the data is `templates` in the JSON.

| Code | What it means | What to do |
|---|---|---|
| `unsupported-number` | a number with a project unit that is not in the data | almost always invented — remove it or back it with a source |
| `unfilled-slot` | an unfilled slot: `{{city}}`, `{city}`, `%CITY%`, `undefined`, `NaN`, `[City]` (when it is a dataset column), lorem ipsum — critical; an empty place in a title or heading — warning | find where the generator got the empty value |
| `llm-leftover` | a model's reply instead of text: a refusal, "As an AI language model", "Certainly! Here is" | regenerate the page, fix the prompt |
| `mojibake` | UTF-8 read as Latin-1: `CafÃ©`, `Weâ€™re` | find the pipeline step that lost the encoding |
| `check-by-eye` | numbers with words that are not in the data, one line per page | read them yourself: some are ordinary phrasing, some are invention |
| `brief-left`, `still-draft` | the page is unfinished | finish it; this is not cosmetic |
| `noindex` | the page is closed to indexing | remove it if the template did that by mistake |
| `nosnippet` | snippets are forbidden | without a snippet the page will not appear in AI-search answers |
| `canonical-elsewhere` | the canonical points at another page | check the template |
| `orphan`, `unreachable` | no inbound links / cannot be reached from home | link from the section's hubs; if the hubs are generated, fix the link list in the generator |
| `broken-link` | an internal link to a page the build does not have | remove the link from the template or generate the page |
| `wrong-link-form` | a link to a page of the build in a form the host does not serve: other case, `/about.html` for `about/index.html`, `/faq/` for `faq.html` | write the link in the page's own form, or add a redirect rule |
| `hub-missing-links` | a section page does not link to some of its pages (one finding per section) | make the section template list every page: a list, alphabetical, or paginated |
| `jsonld-mismatch` | a price, rating or review count in JSON-LD that the page does not show | take markup and text from the same data field |
| `stale-year` | a past year in the title or H1, presented as freshness | drop the year from the template or fill in the current one |
| `title-h1-mismatch` (info), `no-og` (info), `no-viewport` | title vs H1, link previews, phones | one line each in the template |
| `heavy-html`, `heavy-images` | HTML over 2 MB (Googlebot reads 2 MB), images over 1 MB | move embedded data out of the page; compress images |
| `near-duplicate` | overlap above the duplicate threshold | see "Near-duplicates" below |
| `similar` | alike, but below the duplicate threshold | worth a look, **not a finding**: do not set a canonical from it |
| `low-uniqueness` | the template crowded out the content | add the page's own row data |
| `template-skeleton` | the same H2s in the same order | vary the structure with the data, not just the substitutions |
| `same-opening` | the same opening sentence | rewrite the first paragraph in the template |
| `thin` | little text | see "Thin pages" below |
| `no-title`, `no-h1`, `many-h1`, `no-headings` | heading structure | fix the template |
| `title-short`, `title-long`, `no-description`, `description-length` | lengths | cheap; build the description from the row's fields, with no new numbers |
| `duplicate-title`, `duplicate-description` | shared across several pages | collapsed in the results; often rows with one intent |
| `deep` | too many clicks from the home page | move it up in the structure |
| `vague-anchor` | anchors like "here", "read more" | replace with descriptive ones |
| `source-note` | a note about the file: encoding, frontmatter | fix these first: while a file is read wrongly, every other finding on it is unreliable |

What collapses on its own: a closed section (20 pages or more, at least 90% of
them noindex) is one note, not a finding on every page; noindex together with a
canonical on one page is one finding; a print copy or a variant canonicalised to
an open page in the same language is an info line.

Machine readability (switch it off with `--no-aeo`):

| Code | What it means |
|---|---|
| `js-shell` | almost no text in the source HTML against a pile of scripts; AI-search crawlers do not execute JavaScript |
| `answer-preamble`, `answer-short`, `answer-long`, `no-answer` | the first paragraph is a run-up, outside the quotable range, or not found |
| `no-question-headings` | fewer than a third of the subheadings are questions |
| `long-paragraph`, `no-structure` | the block is hard to quote whole |
| `jsonld-broken`, `jsonld-faq-invisible`, `jsonld-no-type` | markup does not parse, does not match the text, or has no `@type` |
| `no-date`, `no-author` | no machine-readable date and author. The date is a real publish or update date from the data, never the build date |
| `robots-blocks-page` | a Disallow rule in robots.txt blocks a page in the build (critical) |
| `ai-crawler-blocked`, `robots-blocks-all` | robots.txt blocks a crawler you need, or the whole site |
| `robots-unreadable`, `no-robots`, `robots-no-sitemap` | robots.txt was not read, not found, or has no `Sitemap:` line |
| `img-no-alt` | images without alt text |

robots.txt is looked for next to the pages and one level up; the path goes in
`--robots`. It has to sit in the publish root — the directory served as `/`; if
that directory is generated, the generator emits robots.txt. A file one level up
that never deploys satisfies the check but not the site. `X-Robots-Tag: noindex`
is read from `_headers`, `netlify.toml` and `vercel.json`.

Language versions:

| Code | Level | What it means |
|---|---|---|
| `hreflang-no-self` | critical | the cluster does not include the page itself — the cluster is invalid |
| `hreflang-no-return` | critical | the link is not mutual; a one-sided one is discarded |
| `hreflang-canonical-conflict` | critical | the canonical points at another language while hreflang calls the versions equal |
| `hreflang-static-cluster` | critical | the template prints one identical cluster on every page |
| `translations-parked` | critical | translations closed with noindex and canonicalised to the original; one line with a count per language — decide language by language |
| `hreflang-missing` | warning | the site has several languages and this page does not say so |
| `hreflang-bad-code`, `hreflang-lang-mismatch` | warning | a bad code or an empty href; the language does not match the text |
| `hreflang-target-blocked` | warning | the cluster points at a page closed to indexing |
| `hreflang-unknown-target` | info | an address in the cluster is not among the pages |
| `stale-closed` | info | the date has passed and the page is already closed to indexing — as it should be |

## About invented numbers

The most important finding in the package: a hundred pages carrying fees and
deadlines that do not exist harm the person who acts on them.

A number carrying a unit derived from the dataset (USD, m², kW) is `critical`.
A number with any other word — "12 years", "3,500 orders" — goes into one
`check-by-eye` line: a weaker signal, but invention hides there. Forgiven: a
number from the page's own row, and site constants — values standing in one
column across most rows. Nothing else is forgiven, however many pages repeat it.

**Every generated page must name its row.** In Markdown: `keyword:` in the
frontmatter. In HTML: `<meta name="keyword" content="…">` in the template.
Otherwise the row is looked up by slug and title, and often not found. If N in
"Checked against the dataset: N of M" is lower than the number of row pages, fix
the binding first: a clean check on three pages out of forty means nothing. Hub
and home pages without a row are expected.

A number in a brief is normalised (`1200`, `15 %`); the page may say `1,200` or
`15%` — search the template for both. False positives happen: a legitimate
number can be absent from the dataset. Go through them with the person.

## A gate for CI

```bash
indexgap check --strict                                    # non-zero exit on critical
indexgap check --out indexgap-baseline.json                # once; commit the file
indexgap check --baseline indexgap-baseline.json --strict  # fails only on new critical
```

GitHub Action: `uses: borisowlexa2010-star/IndexGap@v1.16.0` with `root`,
`site`, and optional `baseline` and `args`.

## Before a deploy

```bash
indexgap diff ./prod-build ./out --site https://example.com --strict
```

Compares the build in production with the new one: pages that disappear
(`page-removed` — critical if it was indexable and no rule in `_redirects`,
netlify.toml or vercel.json covers it), pages that close (`page-closed`),
title/H1/description changed on most pages of a template (`template-change`),
text cut by more than half (`text-shrunk`), new pages, and new critical `check`
findings (`new-finding`). Do not "fix" a missing page by deleting the links to
it: ask the person whether to bring it back or add a 301.

A finding the person accepts on purpose goes into `indexgap.json` as
`"ignore": {"no-viewport": ["/print/*"]}` — never silence a finding
without asking. If the run says `dataset-unbound`, the dataset is not joined
to the pages: no number was checked, so do not report the facts as verified.

## Repair briefs

```bash
indexgap brief ./out --site https://example.com --dataset keywords.csv --write
```

Lays the findings out as work orders in `indexgap-briefs/`: what to do, the
profile's thresholds, and the dataset row — the only permitted source of
numbers. Without `--write` it is a dry run. Briefs are overwritten on every
run — they are a report; keep your edits in the source the pages are built
from. Each brief ends with the check command that produced it, `--dataset` and
profile included; run it after the rebuild. Without `--dataset` the fact check
silently drops out.

Order:

1. `_template.md` — what fires on nearly every page: one template edit instead
   of hundreds. It may be missing (fewer than 20 pages, or hubs dilute the
   share) — then the same code with the same message on most page briefs is
   still one template fix.
2. `_site.md` — robots.txt, markup, the links between language versions.
3. `_duplicates/<first-page>.md` — near-duplicate groups, one file per group named after its first address; see below.
4. Page briefs, heaviest first (`--limit`, 50 by default; `0` means all).

**Near-duplicates.** If the pages in a group come from *different* dataset rows
(a different city, service or product), the template is what duplicates them,
not the intent. Fix the template: more of each row's own data, sections that
depend on the data. Never set a canonical between such pages — real pages would
drop out. Canonical or merge only rows with the same intent; `indexgap plan`
reports those, and the fix is removing the extra row from the dataset. Links
between the duplicates are not a fix (a link does not make two pages
different), but keep the normal sibling and hub navigation.

**Thin pages (`thin`).** A hub, a listing and the home page are judged by their
links, not their word count: never close them to indexing. For a row page, add
facts from its row; if the row has none, ask the person whether the page should
exist. The threshold is `checks.thin_words` in `indexgap.json`; to silence the
finding for a content type that is legitimately short, **lower** it. Do not pad
the text to reach it.

**The package does not write the text, and must not.** The central check
compares the numbers on a page with the dataset row; if the package supplied
them, the check would be checking itself. A fixed page holds no number that is
absent from its row — no data, no section.
