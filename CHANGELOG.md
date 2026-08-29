# Changelog

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
