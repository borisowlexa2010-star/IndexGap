# Changelog

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
