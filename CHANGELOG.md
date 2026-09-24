# Changelog

## 1.8.0 — 2026-09-24

Three things a live Search Console export of rumors.app showed the tool
getting wrong or keeping to itself.

* **The engine's addresses that are not on the site are finally shown.** The
  funnel counted them and printed them nowhere — not in the console, not in the
  HTML. On rumors.app there were nine, and among them a staging host and an
  internal GitLab: the most important thing in the export never reached the
  person reading it. They are now listed by meaning — other hosts, grouped (the
  ones to close with `X-Robots-Tag: noindex` or a login), pages that no longer
  exist (redirect those with traffic), and files.
* **Every network request introduces itself.** Without a header urllib sends
  `Python-urllib/3.x`, which many firewalls refuse by default: the rumors.app
  sitemap answered the tool 403 and answered curl 200, and the report blamed the
  site. Sitemaps, IndexNow, the engine registry and the AI APIs now send
  `indexgap/<version> (+repository URL)`. The tool does not pretend to be a
  browser — a site is entitled to know who is asking, and to say no.
* **More than one sitemap.** `--sitemap` can be repeated, and when robots.txt
  declares sitemap files that were not passed, the tool names them with the
  exact flags to add. One `sitemap.xml` held 13 URLs; the three files robots.txt
  declared held 94, and the "in sitemap" step had been low by a factor of seven
  without a word about it. A broken file no longer hides the others.

357 tests on 3.9, 3.12 and 3.14.

## 1.7.0 — 2026-09-22

AI citations, observed rather than measured: Bing Webmaster Tools publishes
which pages Microsoft Copilot cited, and `doctor` now reads it.

* **New evidence kind: citations in AI answers.** Bing Webmaster Tools → AI
  Performance → Pages exports `"Page","Citations"`. Pass it like any other
  export — `--indexed ai-performance-pages.csv` — and the funnel gains a last
  step after the index: which pages Copilot actually cites. The format was taken
  from a live account, not guessed: every field quoted, `\r\n` line endings.
* **It is not merged into the index step, on purpose.** The export is a sample:
  on the live visa catalogue, 93 cited pages against more than a thousand
  indexed. Merged into the index, it would have declared everything else
  unindexed — the most expensive kind of confident wrong answer. Citation is its
  own step, it reports no "lost", and the report says that silence in it proves
  nothing about indexing.
* **What it shows that nothing else does.** Pages the AI still cites although
  you closed them from search — for pages closed under a payment provider's
  policy, that is not a traffic question. Cited pages that are missing from the
  sitemap. Cited pages that are no longer on the site at all. And the most-cited
  pages, with counts. On the live catalogue: 93 pages, 12,482 citations, and a
  Chinese guide cited 809 times.
* **Recognised by its signature column.** `Citations` appears in no other
  tool's export, so the source is identified with confidence and ahead of the
  file name — `bing-*.csv` became ambiguous the day Bing started offering two
  exports. The queries export from the same screen (`Grounding Query`) holds no
  page addresses; read silently it would have said "nothing is cited", so it is
  refused with the name of the tab to export instead.
* `doctor` no longer refuses to run with nothing but a non-panel export: a
  citations file alone is enough to build a funnel.

344 tests on 3.9, 3.12 and 3.14.

## 1.6.0 — 2026-09-22

The first run against a live Next.js site reported 12,556 critical findings.
About 600 were real. This release is what it took to say so.

* **A redirect stub is no longer taken for the home page.** Next.js serves the
  site root as a stub whose only content is `NEXT_REDIRECT;replace;/en;307;`.
  Taken for the home page, it had no links out, so about three thousand pages
  were declared unreachable. `NEXT_REDIRECT` and `meta refresh` are now
  followed to the real home, the report says so, and the stub itself is not
  counted as an orphan.
* **New site-level check `translations-parked`.** The site had closed 1,408
  translations with `noindex` and pointed their canonical at the English
  original — a holding pattern its own history introduced as temporary for two
  languages, two and a half months earlier. Page by page, that one rule
  produced 9,722 findings across seven checks: nine tenths of the report, with
  the one thing worth knowing buried in its own consequences. It is now one
  finding with a count per language, and it says whether the parked pages still
  declare hreflang, which is the part that actually contradicts the canonical.
  Five or more such pages make a rule; fewer are reported one by one as before.
* **Reachability is not judged on pages closed from the index.** Links exist so
  that a page is found and indexed; a `noindex` page has declined that. It no
  longer collects `orphan`, `unreachable` and `deep` on top of `noindex`, which
  stays.
* **Site-level findings lead "Fix in this order".** The list ranked by count
  only, so a site-level finding — always a count of one — never made it. That
  included `robots-blocks-all`, the most expensive finding in the package: a
  robots.txt closing the site to every engine lost its place to fifty thin
  pages. Site-level findings now come first, labelled `site` instead of `1`.

On the live site: critical 12,556 → 750, warnings 1,260 → 216, orphans
1,393 → 0. What is left is real: 55 near-duplicate groups, 40 indexable pages
with no link path to them, and 116 closed English pages worth a second look.
333 tests on 3.9, 3.12 and 3.14.

## 1.5.1 — 2026-09-15

The export Google Search Console actually hands you now works.

* **The Export button in Search Console gives you a zip, not a CSV**, and that
  zip holds `Pages.csv`, `Queries.csv` and the rest. Both zip and xlsx begin
  with the same two bytes, so the archive was routed into the workbook reader
  and came back as "the workbook has no sheets" — an error with no path from it
  to a fix, on the single most common data source there is. A zip without an
  `xl/` directory is now read as an archive of tables.
* **The sheet is chosen by content, not by name.** Search Console translates
  the file names inside the archive — the Russian panel ships `Страницы.csv` —
  so the sheet with the most address-shaped cells wins, and the queries sheet
  loses because it holds no addresses at all.
* **An archive with nothing readable in it says so**, and says what to do
  instead, rather than talking about sheets that were never the point.

## 1.5.0 — 2026-08-29

The first release meant to be installed rather than cloned, and the bug that
had to be fixed before it could be.

* **Reading a one-column CSV no longer depends on the Python version.** The
  single-column path told `csv` that the delimiter was NUL — a way of saying
  "there is no delimiter here". CPython stores the delimiter as a code point
  and reserves 0 for "not set", so Python 3.9 refused it outright and the read
  died with a `TypeError`. On 3.11+ the same trick was accepted as a real
  delimiter, which was worse: a value containing a NUL was split in two and
  nothing said so. The delimiter is now a control character verified absent
  from the file's own text, and a single-column file reports no delimiter at
  all, the way the xlsx path already did. 302 tests.
* **Install instructions that match reality.** The README promised
  `pip install indexgap` for a package that is not on PyPI yet — the first
  thing a visitor would try, and it would fail. Both READMEs now mark that
  line and show the source install beside it.
* **Repository hygiene.** The repository archive is no longer tracked, and the
  package metadata points at the repository under its actual name.

## 1.4.0 — 2026-08-29

`indexgap brief` — the check's findings turned into work orders, without the
package writing a word of the text.

* **New `brief` command.** A report answers "what is wrong with me"; a brief
  answers "what do I do". Each finding now carries an imperative fix, and the
  findings are laid out as markdown files next to the pages they belong to,
  ready for a person or an agent to pick up.
* **It still writes no text, deliberately.** This is not caution. The package's
  central check compares the numbers on a page against the row of the dataset
  that produced it. If the package supplied those numbers itself, the check
  would be checking its own output and would always be green.
* **Three placement rules, or it would just be the report again.** On the live
  2,970-page catalogue the check reports 6,074 findings; `brief` writes 966
  work orders. A finding that fires on nearly every page (or nearly every page
  of one language) is a property of the template and gets one brief, not 2,919.
  Near-duplicates are fixed as a group — a single page out of a group of 17
  cannot be fixed alone — so 588 duplicate findings become 72 group briefs.
  robots.txt, markup and hreflang clusters belong to the site, not to a page.
* **Each brief carries what the fix has to satisfy**: the profile's thresholds,
  the dataset row as the only permitted source of numbers, and the command that
  verifies the result. Thresholds come from the project's own config, so a
  brief never asks for 250 words where the check demands 400.
* **Dry run by default**, like `notify` and `cite`: it says how many briefs it
  would write and where, and creates nothing without `--write`. `--limit`
  (50 by default) keeps the heaviest pages first — 892 briefs is not a task
  list, it is a second report. 20 new tests (301 total).

## 1.3.0 — 2026-08-29

`indexgap cite` — measuring whether AI search cites you, and one bug the work
uncovered.

* **New `cite` command.** Asks Perplexity, the OpenAI Responses API, the Gemini
  API and Grok a set of real user questions and counts how often your domain
  comes back in the sources. It is the only part of the package that needs API
  keys and costs money, so it is a separate module, off by default, and sends
  nothing without `--send` — a dry run first states how many calls it would
  make and on whose bill.
* **It reports a share, never yes/no.** These answers are not deterministic:
  the same question twice returns different sources. Each question is asked
  several times and the table shows how many runs cited you. It also records
  who was cited instead, and brand mentions without a link.
* **It never claims the product.** What is measured is the API. OpenAI's own
  documentation says search is triggered by a tool and the model decides
  whether to search, which is not how ChatGPT behaves; Gemini's API grounding
  is not AI Overviews. Nowhere does the output say "ChatGPT cites you"; it says
  how many runs out of N through a given API returned your domain. Every report
  repeats that being cited is driven off-site — 0.66–0.74 correlation with
  mentions elsewhere against 0.19 with page count.
* **Fixed: `tr()` at module level froze the language at import.** Tables of
  finding descriptions, profile titles and source labels were translated when
  the module loaded — before `--lang` was parsed. `indexgap profiles --lang ru`
  printed a Russian heading with English profile names. A half-translated report
  looks broken, which is worse than either language. Those tables now hold the
  key, marked with a no-op `N_()` so the catalogue still sees them, and are
  translated at print time. 20 new tests (281 total).

## 1.2.0 — 2026-08-29

Multilingual and multi-region sites. The previous versions did not support
them — they quietly damaged them, and running against a live 2,970-page
catalogue in ten languages showed exactly how much.

* **Script, not the declared language.** Text volume and title/description
  lengths are now measured by the script of each page, in display width.
  Before, one project language was detected by majority and overrode every
  page: on the live catalogue it was `en`, so all 289 Chinese pages were
  counted as English — 201 "words" instead of 654. **All 174 `thin` findings
  on that site were false, and all 174 were Chinese.** Width also handles what
  a per-language factor could not: mixed strings, and the live catalogue's
  Chinese titles are only 43% Han, the rest Latin brand names and "Form 14A".
* **Anchor length is judged only where length means something** — Latin,
  Cyrillic, Greek. **All 914 `vague-anchor` findings on that site were false**:
  «यमन» (Yemen) and «হোম» (Home) are three characters and whole words. Not one
  English page had the finding. For scripts with no vague-word list the tool
  now says nothing, which is more honest than 295 findings out of 296.
* **New `hreflang` module.** Missing self-reference, one-way links (Google
  discards the whole cluster, it does not count them partly), alternates
  pointing at noindex or foreign-canonical pages, a canonical that leaves the
  language and cancels the cluster, missing `x-default`, and language codes
  where a country code was meant (`uk` is Ukrainian, not the United Kingdom).
  It stays silent on monolingual sites.
* **Geo: same language, different country is not a duplicate.** `en-us` and
  `en-gb` are legitimately near-identical, and the old advice — "keep one, set
  a canonical" — would have killed the regional version. Pairs inside one
  hreflang cluster are excluded from duplicates and reported as their own line.
* **A finding covering one language is named as such.** On the live site
  `description-length` hit 289 of 289 Chinese pages: 10% of the site and 100%
  of the language. The first number means nothing, the second means the Chinese
  template was written to Latin lengths.

* **A hardcoded cluster is one finding, not thousands.** Two of the six live
  sites print the home page's hreflang cluster on every page, self-reference
  missing. That produced 5,498 findings on 1,100 pages — three per page for one
  template bug. Now it is a single line naming the cause; on that site the
  hreflang findings went 5,498 → 4.

Measured on that site: findings 7,200 → 6,074, `thin` 174 → 0, `vague-anchor`
914 → 0, `title-long` 275 → 80. 19 new tests (261 total).

## 1.1.0 — 2026-08-29

English output. The package was written in Russian, and Russian stays the
source language of every message — the translation key *is* the Russian string,
so the Russian output costs nothing and cannot drift from the code.

* **`indexgap --lang en`**, `INDEXGAP_LANG`, or your system locale. With no
  signal at all the output is English: the package lives on GitHub, and someone
  whose locale is unset is more likely reading English. A locale from the
  post-Soviet region gets Russian, since no translation of its own exists yet.
* **478 strings** translated: the CLI, the HTML report, all 49 finding-code
  descriptions, `--help`, every error message, the content-type profiles.
  A missing key prints in Russian rather than crashing the command.
* **English skills.** `indexgap init` installs `SKILL.en.md` when the language
  is English, and falls back to the Russian skill where no translation exists.
* **Language data is not translated, and that is enforced by a test.** The
  codemod that marked the strings also wrapped Russian stopwords, word endings,
  counting words and export-header hints. Translating those would have silently
  broken the checks for Russian sites whenever the report was read in English —
  a failure invisible in the output. They were unwrapped, and `test_i18n` pins
  them.
* 25 new tests (242 total), including one that runs every command in English
  and fails on a single Cyrillic character anywhere in the output.

## 1.0.0 — 2026-08-29

First stable release. The eight commands, the finding codes and the shape of
`indexgap.json` are now a promise: they will not change without a major
version. What is still open — calibration of the `events` and `ugc` profiles
against live material, and messages in languages other than Russian — needs
no interface change, which is why 1.0 is honest rather than early.

This release also reads any tool's export, not just a webmaster panel — and
the report never pretends they mean the same thing.

* **New `sources` module.** Recognises exports from Ahrefs, Semrush, Serpstat,
  Moz, Screaming Frog, Sitebulb, JetOctopus, OnCrawl, Netpeak, GA4, Matomo,
  Plausible, Umami, Cloudflare and the five webmaster panels — by filename
  first, headers second. A tie answers "I don't know" rather than inventing a
  label, because two exports under one label silently merge into one index.
* **Formats read as they come**: CSV with any delimiter and encoding, **XLSX
  without re-saving** (stdlib `zipfile` + XML — still zero dependencies), JSON,
  NDJSON, an XML sitemap, or a plain list of URLs. Relative paths from GA4 and
  Matomo (`/guide/visa/`) are completed against `--site`; without `--site` the
  file is no longer read as silently empty.
* **Each source keeps its meaning.** A panel answers "does the engine know this
  page". Analytics proves indexation only for pages someone visited. A crawler
  proves reachability. Ahrefs is *its* index, not Google's. The funnel step is
  renamed to match the evidence, a crawler export next to a panel triggers an
  explicit "this number is higher than real indexation", and engine-vs-engine
  comparison runs over panels only.
* **The keyword column is found** whether an export calls it `Keyword`, `Фраза`,
  `Запрос`, `Search Term` or `Query`; `--dataset` accepts XLSX too.

21 new tests (217 total).

## 0.6.0 — 2026-08-28

Calibrated against six production sites: 7,149 sitemap URLs, 5,041 pages
fetched and parsed. The run changed the tool in three ways.

* **One cause, not four findings.** Two of the six sites served every page as
  an empty JavaScript shell, and the tool reported 1,099 `js-shell` *and*
  1,099 `low-uniqueness` *and* 1,098 `orphan` — one disease counted four times.
  `checks.is_shell()` now decides once, checks that need text or links are
  skipped on a shell, and the run states how many shells it found.
* **Duplicates are groups, not pages.** 588 near-duplicate pages turned out to
  be 72 connected groups, the largest holding 24. The group count is now
  reported alongside the per-page findings.
* **A finding on ≥90% of pages is a template property.** `vague-anchor` fired
  on 2,970 of 2,970 pages; the culprits were a language switcher (`中文`) and a
  social link (`VK`). Anchor length is now measured with a CJK-aware rule and a
  short allow-list, and `checks.template_wide()` labels any code that hits
  almost every page as something to fix once in the template.

Also: thresholds in `profiles.py` are documented against the measured
percentiles instead of being asserted; 19 new tests (196 total).

## 0.5.0

* `indexgap init` — install into a project: detects the content directory,
  site URL, content type and dataset, writes `indexgap.json`, copies the four
  agent skills into `.claude/skills/`, extends `.gitignore`, optionally writes
  a marked block into `AGENTS.md`. Nothing project-specific is ever copied
  between projects, and the IndexNow key least of all.
* Bare `indexgap check` picks up what `init` recorded.
* Renamed from `pseo-kit`.

## 0.4.0

* Content-type profiles: `catalog`, `events`, `ugc`, `product`.
* `indexgap portfolio` — one run across several projects, shared problems
  reported as a share of each project's pages.
* `freshness` — `stale-event` for a passed date on a still-indexable page.
* Second adversarial review wave: 44 reproduced defects, several of them
  regressions introduced by the first wave's repairs.

## 0.3.0 and earlier

First adversarial review wave; URL key normalisation, encoding detection,
MinHash + LSH near-duplicate detection, bigram uniqueness, two-tier fact
verification, content-hash `lastmod`, IndexNow, the indexing funnel.
