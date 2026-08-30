---
name: indexgap-review
description: >
  Review generated pages before publishing: invented facts, near-duplicates,
  template seams, orphans with no inbound links, thin pages, machine
  readability for AI search. Use after generating content and before
  building the sitemap.
---

# The pre-publish review

```bash
indexgap check ./content --site https://example.com --dataset keywords.csv
```

`--site` is the full site address including the scheme. It also determines the
home page: if the home page is not among the parsed files, click depth is not
computed and the command says so. A different home page goes in `--home`.

`--dataset` switches on fact-checking against the row data. Without it the text
checks still run, but there is nothing to verify numbers against.

The report is written to `indexgap-check.html` and `indexgap-check.json`. The
`doctor` command writes to its own files and never overwrites this one.

## What to look at first

The command prints the top three causes itself — start there. The full table of
codes:

| Code | What it means | What to do |
|---|---|---|
| `unsupported-number` | a number with a project unit that is not in the data | almost always invented — remove it or back it with a source |
| `check-by-eye` | numbers with words that are not in the data, one line per page | read them yourself: some are ordinary phrasing, some are invention |
| `brief-left`, `still-draft` | the page is unfinished | finish it; this is not cosmetic |
| `noindex` | the page is closed to indexing | remove it if the template did that by mistake |
| `nosnippet` | snippets are forbidden | with no right to a snippet the page will not appear in AI-search answers |
| `canonical-elsewhere` | the canonical points at another page | check the template |
| `orphan`, `unreachable` | no inbound links / cannot be reached from home | link to it from the section's hub pages |
| `near-duplicate` | overlap above the duplicate threshold | rewrite for a different intent, or keep one and point the canonical at it |
| `similar` | alike, but below the duplicate threshold | worth a look, **not a finding**: do not set a canonical from it. The loss breakdown ignores it too |
| `low-uniqueness` | the template crowded out the content | add what makes this page different |
| `template-skeleton` | the same H2s in the same order | vary the structure with the data, not just the substitutions |
| `same-opening` | the same opening sentence | rewrite the first paragraph |
| `thin` | nothing to index | fill it out, or raise the threshold in the config |
| `no-title`, `no-h1`, `many-h1`, `no-headings` | heading structure | fix the template |
| `title-short`, `title-long`, `no-description`, `description-length` | lengths | cosmetic, but cheap |
| `duplicate-title`, `duplicate-description` | shared across several pages | they get collapsed in the results |
| `deep` | too many clicks from the home page | move it up in the structure |
| `vague-anchor` | anchors like “here”, “read more” | replace with descriptive ones |
| `source-note` | a note about the file: encoding, frontmatter | fix these first: while a file is read wrongly, every other finding on it is unreliable |

Machine readability (switch it off with `--no-aeo`):

| Code | What it means |
|---|---|
| `js-shell` | almost no text in the source HTML against a pile of scripts; AI-search crawlers do not execute JavaScript |
| `answer-preamble` | the first paragraph is a run-up, not an answer |
| `answer-short`, `answer-long` | the first paragraph is outside the quotable range |
| `no-question-headings` | fewer than a third of the subheadings are questions |
| `long-paragraph`, `no-structure` | the block is hard to quote whole |
| `jsonld-broken`, `jsonld-faq-invisible` | markup does not parse, or does not match the text |
| `no-date`, `no-author` | no machine-readable date and author |
| `ai-crawler-blocked`, `robots-blocks-all` | robots.txt blocks a crawler you need |
| `robots-unreadable`, `no-robots` | robots.txt was not read or not given |
| `no-answer` | no paragraph that could be quoted |
| `img-no-alt` | images without alt text |
| `jsonld-no-type` | the markup block has no `@type` |
| `robots-no-sitemap` | robots.txt has no `Sitemap:` line |

robots.txt is looked for next to the pages and one level up; the path goes in
`--robots`.

## About invented numbers

This is the most important finding in the package, and the only one where being
wrong costs more than lost traffic. A hundred pages carrying fees and deadlines
that do not exist harm the person who acts on them.

The check has two tiers. A number carrying a unit derived from the dataset
(USD, m², kW) is `critical`. A number with any other word — “12 years”, “3,500
orders”, “25 tonnes” — is collected into a single `check-by-eye` line at the
minor level: a weaker signal, but most invention hides exactly there.

Forgiven: a number from the page's own dataset row, and site constants — the
ones repeating in a single column across most rows (a fixed fee, a warranty
period). A number that is in neither place is never forgiven, no matter how
many pages repeat it.

Watch the "Checked against the dataset: N of M" line. If N is lower, find out
why: the page either did not match a row, or matched several at once — in the
second case the check honestly does not run, and it says so separately.

False positives are possible: a number can be legitimate and simply absent from
the dataset. Go through each one with a human; do not silently edit.

## A gate for CI

```bash
indexgap check ./content --site https://example.com --dataset keywords.csv --strict
```

Exits non-zero when there are critical findings, so the pipeline does not
publish something unfinished.

## Repair briefs

```bash
indexgap brief ./content --site https://example.com --dataset keywords.csv --write
```

Lays the same findings out as work orders in `indexgap-briefs/`: each carries an
imperative "what to do", the profile's thresholds, and the dataset row — the
only permitted source of numbers for that page.

Read the briefs in this order:

1. `_template.md` — what fires on nearly every page. That is one edit to the
   template, not hundreds of edits to pages. Always start here: some of the
   other briefs disappear on their own once it is done.
2. `_site.md` — robots.txt, markup, the links between language versions.
3. `_duplicates/group-NNN.md` — near-duplicate groups. The brief is written for
   the group: a single page out of one cannot be fixed alone. Keep one, pull the
   rest apart by intent, and do **not** link them to each other.
4. The remaining files — one per page, heaviest first (`--limit`, 50 by
   default; `0` means all of them).

Without `--write` this is a dry run: the command says how many briefs it would
write and where, and creates nothing.

Briefs are overwritten on every run — they are a report, not a source file.
Keep your own edits in the pages.

**The package does not write the text, and must not.** It states the task; you
write the words. The reason is not caution: the central check compares the
numbers on a page against the dataset row, and if the package supplied those
numbers itself the check would be checking its own output and would always be
green. A fixed page must contain no number that is absent from its dataset row
— if the data is not there, the section is not written at all.
