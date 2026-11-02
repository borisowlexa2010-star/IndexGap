---
name: indexgap-cite
description: >
  Whether AI search sees the site and cites it: AI crawlers from the server
  logs, a citation measurement in ChatGPT, Perplexity, Gemini and Grok, a
  comparison with the previous measurement, and gaps by section. Use when the
  person asks about AI search, AI Overviews, ChatGPT, Perplexity, citations,
  GEO/AEO, "AI answers never mention us", "do AI bots visit us", "is
  Cloudflare blocking AI crawlers".
---

# AI search: does it see the site, does it cite it

Go from free and exact to paid and sampled. Do not start with `cite --send`:
it is the only part of the package that spends the person's money, and without
the first two steps its number has nothing to stand on.

## 1. Logs: which AI bots come at all

```bash
indexgap doctor ./public --site https://example.com \
  --sitemap ./public/sitemap.xml --logs /var/log/nginx/access.log
```

`--logs` can be repeated, `.gz` is read as is, and both the combined format
(nginx, Apache) and CDN JSON lines (Cloudflare, Vercel, Fastly) are understood.
No keys, no network.

Read the "Bots in the logs" table by its "why it comes" column:

- **AI search** (OAI-SearchBot, Claude-SearchBot, PerplexityBot) builds the
  index the assistant takes answer sources from. Its absence is the main gap.
- **AI on a person's request** (ChatGPT-User, Claude-User, Perplexity-User):
  someone asked a question and the assistant opened the page. This is the
  closest thing to a citation that the logs can show.
- **Training** (GPTBot, ClaudeBot, CCBot) does not affect today's answers and
  is not counted in "Opened by AI search".

What to do with the findings:

- "N of N requests got 401/403" for an AI search bot is almost always CDN or
  WAF protection, not robots.txt. Tell the person plainly: the pages are closed
  to that AI search even though robots.txt allows them. It is fixed in the CDN
  settings (Cloudflare has rules for AI bots), not in the site's code.
- "Gaps by section" marked "← the gap is here" in the AI block is a section AI
  search visits noticeably less than the rest of the site. Look for the
  section's shared cause: hub links to it, `noindex`, a JS shell (`js-shell`
  in `check`).
- No AI search bot at all: the site is invisible to AI answers for now. Check
  robots.txt (`ai-crawler-blocked` in `check`) and the CDN before measuring
  citations; measuring now spends money to get zero.

A User-Agent can be faked. Read the numbers for rare bots with that caveat,
and do not present them as verified.

## 2. Measuring citations: only with the person's consent

First a dry run. It sends nothing and counts the calls:

```bash
indexgap cite --domain example.com --dataset keywords.csv --limit 10
```

Show the person the number of calls and providers and **ask whether to spend
the money**. Do not add `--send` without an explicit yes. The questions must be
real ones, what a person asks ("where to get a Singapore visa"), not "tell me
about company X": citations happen in answers to questions, not to a query
about the brand.

```bash
indexgap cite --domain example.com --dataset keywords.csv --limit 10 \
  --runs 5 --send --out cite-2026-11.json
```

How to read it:

- A share of runs, not yes/no: one answer is nondeterministic. With three runs,
  "1 of 3" and "2 of 3" cannot be told apart, so draw no conclusion from one
  question.
- It measures the API, not the app. What a person sees in ChatGPT overlaps
  with it but is not equal. Say so.
- "Instead of you" is who gets cited for the question. That is the list of
  competitors in AI answers, and it often differs from the ordinary results.

## 3. Comparing with the previous measurement

```bash
indexgap cite --baseline cite-2026-10.json --against cite-2026-11.json
```

It sends nothing. A change in share is marked "notable" only when an exact
Fisher test tells it from noise (p ≤ 0.1); otherwise it says "within noise".
Do not call growth what is marked as noise. To make a shift distinguishable,
add `--runs`; repeating the same measurement does not help.

A fresh measurement can be compared right away: `--send --baseline old.json`.

## 4. Citations in the funnel

```bash
indexgap doctor ./public --site https://example.com --sitemap ./public/sitemap.xml \
  --logs access.log --cite cite-2026-11.json
```

Cited pages join the funnel and the "cited" column of gaps by section. Look at
two findings:

- "Cited but not in the sitemap": the page works as a source, yet the search
  engine is not asked to crawl it. Add it to the sitemap.
- A cited page closed from the index: the owner removed it, and AI keeps
  linking to it. Ask whether that was intended.

No citations is not a loss: the measurement is a sample. Do not mark a section
as a problem only because it was not cited.

## What not to promise

Citations correlate most with mentions of the site outside the site itself,
not with what can be edited in the project's files. The package is a
thermometer: it shows whether AI search sees the pages and how the share moves.
Do not promise more citations from text edits.
