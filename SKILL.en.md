---
name: indexgap
description: >
  The pipeline for programmatic pages from keywords to the index: keyword
  analysis, checking what was written, machine readability for AI search,
  sitemap, IndexNow and a breakdown of lost traffic. Use when someone builds
  many similar pages from data and asks why there is no traffic, why pages are
  not indexed, or how to check that an agent did not invent facts. No API keys.
---

# indexgap

You guide the person through the pipeline: data → pages → index → traffic.
You write the text yourself, and hand everything that can be computed
deterministically to the package. It does not replace you — it catches what
nobody can catch by eye across hundreds of pages.

## First, install it into the project

```bash
indexgap --help          # is the command there at all
cd <project root> && indexgap init
```

`init` works out the pages directory, the site address, the content type and
the dataset, puts the skills into `.claude/skills/` and writes `indexgap.json`.
After that the everyday command is plain `indexgap check`, with no paths or
flags.

**Show the person what `init` detected and ask them to confirm.** It prints
"guessed" wherever it guessed. A wrong pages directory is the most common cause
of the false verdict "every page is an orphan".

No `indexgap` command: install the package with `pipx install indexgap` (from
source, `pipx install -e .` in its directory; without installing,
`PYTHONPATH=<directory> python3 -m indexgap`).

**An IndexNow key does not carry over between projects.** It is bound to the
domain by a file in the site root; someone else's key gets a 403. Mint a new
one with `indexgap init --key`.

## Stages and skills

| Stage | Skill | When |
|---|---|---|
| before generation | `indexgap-plan` | someone brought a CSV of keywords |
| after generation | `indexgap-review` | the pages are written but not published |
| fixing what was found | `indexgap-review` → `indexgap brief` | work orders for the fixes, page by page |
| before a deploy | `indexgap-review` → `indexgap diff` | the new build against the one in production |
| publishing and diagnosis | `indexgap-publish` | sitemap, IndexNow, "why is there no traffic" |
| several sites | `indexgap-portfolio` | the person has a portfolio, not one project |

`indexgap init` installs the skills into the project, under
`.claude/skills/indexgap-*/`. Claude Code reads them on its own. For Codex,
`init` adds a block to an existing `AGENTS.md`; `indexgap init --agents`
creates the file if it is missing.

Open the skill you need in full — the commands and code tables are there.

## Above all: which directory is the site root

Ask this before you run `check`. If the pages live in `./content` and are
served in production as `/services/…`, the input is `./content`, not the project
root. A mistake here gives the most common wrong verdict: every page is declared
an orphan, and the person goes off to add links that are already there. The
package checks for this itself and prints the line "the directory does not seem
to match the site root" — when you see it, fix the path, not the linking.

## And what type of content this is

A catalogue, an events listing, a feed and a landing page break in different
ways, and their thresholds differ in substance, not in taste. Ask, and set the
profile: `--profile catalog | events | ugc | product`. `indexgap profiles`
prints what each one changes.

Two places where the profile decides everything:

* **ugc** switches fact-checking off entirely — the pages do not come from a
  dataset, so there is nothing to check against. Silence from the check here
  means "not checked", not "clean", and you have to say so to the person;
* **events** switches on `stale-event`: a past event left in the index matters
  more than any duplicates.

## And what business this is for

The package is universal; the project is not. Before the first command, look at
the dataset and tell the person what you understood: which niche, which units of
measure, which language. `check` prints this as a "Project — …" line; compare it
with reality and fix `indexgap.json` if it got it wrong.

What changes from project to project, and what you must not assume:

* **fact units** are derived from the dataset and decide which numbers become
  critical findings. Even when there are none, fact-checking still works:
  numbers with any other word are collected into a `check-by-eye` line — a list
  to read through by eye;
* **page structure**. Do not carry sections from an example over to another
  niche. An apartment catalogue, a visa guide and a machine-tool product card
  share no common skeleton;
* **text length**. 250 words is reasonable for a guide and absurd for a product
  card. The threshold is changed in the config, not put up with;
* **language**. For Japanese, Chinese and Thai, length is counted in
  characters, and the title and description length thresholds are their own; a
  Latin-script slug is not built, so if you need readable URLs, add a slug
  column to the dataset.

## Rules shared by every stage

**Invent nothing.** If the row has no data for it, the section is not written.
The `unsupported-number` check catches this, but it is better not to give it
work: a hundred pages with numbers that do not exist harm the person who
trusted them.

**Add internal links.** At least three to neighbouring pages in the section. A
page with no inbound links will not get indexed, even if it is in the sitemap.
Anchors are descriptive, not "here" or "read more".

**The first paragraph is the answer, not a run-up.** It is what AI search and
featured snippets quote. "In this article we will look at" gives them nothing to
quote.

**Change the structure, not just the substitutions.** The same heading skeleton
on every page is a sign of template stamping, even when the words differ.

**Do not remove `keyword` from the frontmatter.** It is what the facts are
checked against the dataset by.

**Remove `status: draft` once the page is finished.** While the mark is there,
the page goes into neither the sitemap nor IndexNow — that is a safeguard, not
an obstacle.

**There is more than one search engine.** Do not reduce the conversation to
Google. IndexNow covers Bing, Yandex, Seznam, Naver and others, but not Google.
Check indexing in every panel where the site is verified: "missing everywhere"
and "missing only in Google" are different diagnoses with different cures.

**The person confirms decisions.** Rejecting keywords, disputed findings,
sending to IndexNow — show them and ask, do not do it silently.

## Be honest about AI search

The package checks that a page **does not get in the way** of a machine taking
an answer from it: it is not closed to snippets or to AI-search crawlers, it is
not an empty JavaScript shell, it contains a direct answer, and its markup is
valid.

It does not promise citations and cannot promise them. According to Ahrefs data
on 75,000 brands, visibility in AI search correlates most strongly with
mentions off the site (0.66–0.74), while the number of pages on the site scores
0.19. 76% of citations in AI Overviews are pages from the top 10 of the regular
results. If the person expects that generating a thousand pages will get them
into ChatGPT answers, say it plainly: getting there is decided by work outside
the project's files.

We do not generate `llms.txt`: Google has said it does not support it and has no
plans to, and no engine has confirmed using it for ranking.

## Fix, do not retell the report

After `check`, do not retell the findings — write the work orders:

```bash
indexgap brief --write
```

They go into `indexgap-briefs/`: first `_template.md` (what is fixed once in
the template), then `_site.md`, then the duplicate groups, then the pages —
heaviest first. The details and the reading order are in the `indexgap-review`
skill.

You write the text, and that is not a formality: the numbers come from the
dataset row attached to the brief. A number that is not there must not be on
the fixed page — if there is no data, the section is not written at all. The
package deliberately does not fill them in itself: otherwise its main check
would be comparing the page with what it wrote itself.

## If the person is a beginner

Do not dump the whole report on them. Start with three numbers — the command
prints them itself under the heading "Fix in this order". Explain what each one
means, and fix one cause at a time. And show them where to see the result for
themselves: Search Console and the other webmaster panels, not this report.
The tool is there so that the person stops needing it.
