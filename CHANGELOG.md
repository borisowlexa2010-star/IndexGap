# Changelog

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
