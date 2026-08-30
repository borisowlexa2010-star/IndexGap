---
name: indexgap-plan
description: >
  Audit the keyword set before generating programmatic pages, and lay out
  stubs carrying a brief. Use when someone brings a CSV of keywords and
  intends to turn it into many similar pages. Catches same-intent keywords
  before they become competing pages.
---

# Planning the pipeline

```bash
indexgap plan keywords.csv --keyword keyword
```

If the package is not installed (`pip install -e .` in its directory), the same
thing runs as `python3 -m indexgap plan …` from the package directory.

It shows how many rows will reach generation and what was rejected: exact
duplicates, slug collisions, identical intents. Row numbers in the report match
the file, header included.

**Intent is the point.** Two keywords meaning the same thing produce two nearly
identical pages, and the engine keeps one of them. Not creating the second is
cheaper than fixing canonicals later.

Two keywords share an intent when their meaningful words match after
normalising word forms: "visa to singapore" = "singapore visa" = "singapore
visas". "singapore visa for indians" is a different intent — it carries a word
the first one does not. The first row of a group is kept.

Show the person the rejected list and ask whether they agree. Do not decide
alone: sometimes a word-identical keyword is a separate intent they can see and
the algorithm cannot. Full breakdown with row numbers: `--json plan.json`.

Once agreed:

```bash
indexgap plan keywords.csv --keyword keyword --out-dir content --write
```

Each file gets frontmatter and a brief carrying the row data. Existing files are
never overwritten — the command is safe to re-run, and it reports how many it
skipped.

**Do not remove `keyword` from the frontmatter when writing the page.** Facts
are later verified through it: without it the check looks the row up by slug and
title, and when that is ambiguous it honestly refuses to verify.

**Remove `status: draft` once the page is finished.** The stub is marked a draft
on purpose: while the mark stays, the page reaches neither the sitemap nor the
IndexNow queue, and `check` reports it as unfinished. Removing the mark is the
last step of writing, not a cosmetic detail.

## What the rejections mean

| Reason | What it means |
|---|---|
| exact duplicate keyword | the row repeats verbatim |
| same intent as another row | see above; the first one was kept |
| slug collides with “…” | different keywords produce the same address |
| empty keyword | the keyword column is blank |
| the keyword contains no letter or digit | junk like `---` or `%%%` |

By default rows with partly empty columns are **not** rejected — the command
only warns which column is empty and in how many rows. If incomplete rows are
useless for this project, switch the threshold on explicitly:
`--min-filled 0.7`.

## A brief for your niche

The default brief deliberately does not dictate the page structure — every
business has its own. If the structure for this project is known and repeatable
(a product card, say), write your own template and pass it in:

```bash
indexgap plan keywords.csv --keyword keyword --out-dir content \
    --brief my-brief.md --write
```

The template can use `{keyword}`, `{keyword_yaml}` (the same, quoted, for
frontmatter), `{variables}`, `{min_words}`, `{min_links}`, `{title_min}`,
`{title_max}`, `{desc_min}`, `{desc_max}`. Any other brace is an error; if you
need literal braces (a JSON-LD example, for instance), double them: `{{` and
`}}`.

## Page addresses

For non-latin scripts a slug becomes a short hash. If you need readable URLs,
add a column of ready-made slugs to the dataset and pass
`--pattern "{your_column}/index.md"` — the column value is used as it is, with
no second transliteration. The column can simply be called `slug`: a value the
dataset provides beats a computed one.

An empty column value in the template is a write error, not "put it at the
root": such rows are skipped with an explanation. The template cannot escape
`--out-dir`.
