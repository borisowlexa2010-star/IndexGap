---
name: indexgap-portfolio
description: >
  One run across several sites at once, plus a combined breakdown of what
  breaks the same way everywhere. Use when the person owns not one site but
  a portfolio — several products, catalogues or feeds — and needs to tell a
  shared habit from a one-off.
---

# Portfolio

```bash
indexgap portfolio projects.json --reports ./reports
```

Separate reports answer "what is wrong with this site". A portfolio answers the
question you cannot see in them: **what breaks the same way everywhere.** The
same hole in internal linking across four different niches is no longer a bug in
one project but a property of how these projects get built. The habit is what
needs fixing.

## Describing the portfolio

Plain JSON; paths inside are relative to the file itself:

```json
{
  "projects": [
    {"name": "visa", "root": "../visa/content", "site": "https://visa.example",
     "profile": "catalog", "dataset": "../visa/keywords.csv"},
    {"name": "eventiq", "root": "../eventiq/events", "site": "https://eventiq.example",
     "profile": "events"},
    {"name": "rumors", "root": "../rumors/content", "site": "https://rumors.example",
     "profile": "ugc"},
    {"name": "reloca", "root": "../reloca/out", "site": "https://reloca.example",
     "profile": "product"}
  ]
}
```

Only `name`, `root` and `site` are required. Optional: `profile`, `dataset`,
`sitemap`, `robots`, `config`, `home`, `keyword`, `out`.

One project failing does not kill the run: it becomes a line in the report and
the rest carry on.

**Each project's `root` must match its site root** — the same rule as for a
single check, and it goes wrong more often here simply because there are more
projects. If one of them suddenly reports "every page is an orphan", check the
path first.

## Profiles

Thresholds differ across content types by substance, not taste. 250 words is
normal for a guide and absurd for an event card; fact-checking is meaningless
where there is no dataset at all. `indexgap profiles` prints all four:

| Profile | For | What changes |
|---|---|---|
| `catalog` | pages from data rows: cities, services, products | fact-checking is primary, duplicate threshold 0.80, thin under 250 words |
| `events` | listings, schedules, venues | duplicate threshold 0.88 (two dates of one tour are legitimately alike), thin under 120 words, `stale-event` switched on |
| `ugc` | feeds, threads, reviews | fact-checking switched off entirely, duplicate threshold 0.92, boilerplate tells you almost nothing |
| `product` | dozens of landing pages, not thousands | duplication is not the issue; the AEO checks are what pay off — a direct answer, question-shaped subheadings, markup |

**The profile sits below whatever the person wrote by hand.** A value in
`indexgap.json` always beats the preset.

For a single site the profile goes in a flag:
`indexgap check ./content --site … --profile events`.

## What to tell the person about the result

**Shared problems come as shares, not counts.** A hundred findings across three
thousand pages and ten across twenty are the same disease at different volumes.
The table puts them side by side as percentages precisely because that is where
the systemic cause becomes visible.

**Site-level findings are separate.** robots.txt and markup belong to the site,
not to pages; a share of pages is meaningless for them, so the table just says
"yes". Do not confuse them with mass findings.

**For `ugc`, say that the check did not run.** If a feed shows no fact findings,
that is not "all good", it is "nothing to check against". The tool prints this
as its own line; say it out loud, or the person will assume it was verified.

**For `events`, dates matter more than duplicates.** An event that has passed
while still open to indexing is not lost traffic but lost trust: someone will
travel to a thing that no longer exists on the strength of your page. That is
what `stale-event` is about, and it has a grace period — a write-up of something
that already happened is legitimate content.

**About "specific to one project".** Findings that appeared in exactly one
project are fixed locally. Do not drag them into the shared conclusions — they
are about that one site.
