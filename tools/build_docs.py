#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Собирает docs/ — сайт документации для GitHub Pages.

Содержание страниц берётся из самого пакета: список проверок, их уровень,
текст находки и текст починки читаются из `indexgap.checks` и `indexgap.repair`
в момент сборки. Значит документация не может разойтись с кодом — а если
проверку переименуют, сборка упадёт на явном месте, а не тихо соврёт.

Руками написано только одно поле — WHY: зачем эту находку вообще чинить.
Его из кода не вывести, и именно оно делает страницу страницей, а не
карточкой в справочнике.

Запуск:  python3 tools/build_docs.py
"""

from __future__ import annotations

import html
import io
import json
import os
import re
import shutil
import sys
import contextlib
from pathlib import Path

os.environ.setdefault("INDEXGAP_LANG", "en")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from indexgap import checks, repair, cli          # noqa: E402
from indexgap import __version__                  # noqa: E402

SITE = "https://borisowlexa2010-star.github.io/IndexGap"
AUTHOR = "Alexey Borisov"
PUBLISHED = "2026-08-29"
REPO = "https://github.com/borisowlexa2010-star/IndexGap"
OUT = ROOT / "docs"


# ── что чинить и зачем ───────────────────────────────────────────────────────
# Единственный текст, которого нет в коде. Одно-два предложения на находку:
# не пересказ сообщения, а причина, по которой за неё стоит браться.

WHY = {
 "unsupported-number":
   "A generated page that states a number absent from its own data row is not "
   "a traffic problem — it is a page that misinforms a reader who came looking "
   "for exactly that number. This is the check the rest of the package exists "
   "to support, and the reason indexgap never writes page text itself.",
 "check-by-eye":
   "Some numbers in a page are ordinary language — “one of the first”, “two "
   "weeks or so” — and some are invented facts wearing the same clothes. The "
   "package refuses to guess between them and hands you the short list instead "
   "of silently picking.",
 "source-note":
   "A claim with a source attached can be verified by a reader and survives an "
   "editor who was not there when the page was generated. A claim without one "
   "has to be taken on trust, and generated pages have not earned it."
   " On a hand-written page a missing source is a stylistic choice. On a generated one it is structural: the text was assembled from a row of data that had a provenance, and the page dropped it. Carrying the source through the template costs one line and turns an unverifiable claim into a checkable one — which also happens to be what an editor needs before approving three thousand pages nobody can read individually.",
 "still-draft":
   "A draft that reached the sitemap is worse than a missing page: search "
   "engines index the unfinished version, and the finished one later competes "
   "with its own placeholder."
   " The mark is doing its job — it is the pipeline around it that ignored it. indexgap treats the draft flag as authoritative in both directions: a page carrying it is kept out of the sitemap and out of IndexNow, and is reported here so that the flag does not quietly hold a finished page back either.",
 "brief-left":
   "A work order or TODO left in the published file is visible to every reader "
   "and to every crawler. It is also the clearest possible signal that the page "
   "was generated and never read."
   " The check exists because the failure is invisible to the person who caused it: a work order reads as ordinary text to whoever generated it and as unfinished work to everyone else. It fires on the markers indexgap itself writes, so a pipeline that runs brief and then publishes without clearing the briefs is caught by its own tooling rather than by a reader.",

 "noindex":
   "A page closed off from indexing earns nothing, no matter how good it is. "
   "When it happens across a template it is usually a staging flag that "
   "survived the move to production."
   " There is a second, worse version of this: the tag lands on a template and closes off every page that template produced, so the site loses a whole section without anything appearing broken. That is why indexgap reports it as critical and collapses it when it fires site-wide — a hundred identical findings would hide the single line that caused them.",
 "nosnippet":
   "Without the right to a snippet, a page can rank and still lose every click "
   "to a competitor whose result shows text. It also removes the page from AI "
   "answers, which quote snippets rather than crawl.",
 "canonical-elsewhere":
   "The page hands its accumulated weight to a different URL and drops out of "
   "the index itself. On a generated site this is nearly always one wrong line "
   "in the template, repeated across every page it produced.",
 "orphan":
   "A page nothing links to is discovered only through the sitemap, crawled "
   "rarely, and treated as unimportant — because in the site's own structure it "
   "demonstrably is.",
 "unreachable":
   "Being in the sitemap is a request; being reachable by links is the answer. "
   "A page a crawler cannot walk to from the home page competes for budget it "
   "will not get.",
 "deep":
   "Every click of depth costs crawl frequency. Pages buried far from the home "
   "page get revisited slowly, so their updates reach the index late.",
 "js-shell":
   "The HTML a crawler receives contains no text at all — the page is drawn "
   "later by JavaScript. Search engines may render it eventually; the crawlers "
   "behind AI answers largely do not, and they see an empty document.",

 "thin":
   "A page with too little text has nothing to rank on and little reason to "
   "exist separately from its neighbours. The honest fixes are to fill it out "
   "or to merge it — padding it with filler makes the page worse and the "
   "problem invisible.",
 "low-uniqueness":
   "When most of a page repeats its template, the part that could rank is the "
   "small remainder. A set of such pages competes against itself for the same "
   "query while none of them says anything the others do not.",
 "template-skeleton":
   "The same headings in the same order across many pages tell a reader — and "
   "a ranking system — that the pages were stamped out. Structure that follows "
   "each row's own data is both better reading and better evidence of effort.",
 "same-opening":
   "The opening paragraph is what gets quoted, previewed and read first. When "
   "it is identical across pages, every one of them makes the same first "
   "impression, and none of them answers its own query.",
 "near-duplicate":
   "Near-duplicates are a group problem: a single page out of a cluster of "
   "twenty cannot be fixed alone. Either one is kept and the rest point at it, "
   "or the whole group is pulled apart by intent.",
 "similar":
   "Weaker than a near-duplicate, but the same shape. Worth reading as a "
   "warning that two keywords with the same intent produced two competing "
   "pages.",
 "long-paragraph":
   "A block that runs long is hard to quote, and quoting is how AI search "
   "surfaces a source. Shorter paragraphs also survive the narrow column of a "
   "phone screen, which is where most of the traffic reads them."
   " The threshold is not a style rule, it is about extraction. A retrieval system takes a passage whole or cuts it, and when it cuts, the sentence that carried the answer can end up split from the sentence that qualified it. Paragraphs sized to be quotable are the cheapest insurance against being quoted wrongly.",

 "no-title":
   "The title is the strongest on-page signal there is, and the line a person "
   "actually clicks. A page without one is represented in search results by "
   "whatever the engine invents for it.",
 "title-short":
   "A very short title leaves the strongest field on the page mostly empty — "
   "room that could carry the query the page was built for.",
 "title-long":
   "A title past the display limit gets cut, and what gets cut is the end — "
   "often the part that distinguishes this page from its neighbours.",
 "duplicate-title":
   "Identical titles across pages make them indistinguishable in results and in "
   "the index. At scale this is a template that never learned to use the row it "
   "was given.",
 "no-description":
   "Without a description the engine writes its own from page text. Sometimes "
   "that is fine; on generated pages it usually surfaces boilerplate, because "
   "boilerplate is what the page has most of.",
 "description-length":
   "A description far outside the usual range is either truncated or too thin "
   "to earn the click. It does not affect ranking directly — it affects whether "
   "the ranking is worth anything.",
 "duplicate-description":
   "The same description on many pages wastes the one piece of copy written "
   "specifically to differentiate them in the result list.",
 "no-h1":
   "The H1 states what the page is about in the page's own words. Without it "
   "the engine falls back to guessing from structure that may not exist.",
 "many-h1":
   "More than one H1 leaves the page's subject ambiguous. Usually it means a "
   "template heading and a content heading were both promoted.",
 "no-headings":
   "A page with no headings is a wall of text: unscannable for a reader and "
   "structureless for anything trying to extract an answer from it.",
 "no-structure":
   "Lists and tables are what get lifted into rich results and AI answers, "
   "because they are the parts of a page whose meaning survives being taken out "
   "of it.",
 "img-no-alt":
   "Alt text is what a screen reader announces and what image search indexes. "
   "On a generated page it is also usually generated — which means it is either "
   "written once properly or missing on every page at once.",
 "vague-anchor":
   "“Read more” tells neither a reader nor a crawler what is on the other side. "
   "The anchor is one of the few places where you get to say what a page is "
   "about from outside the page.",

 "hreflang-missing":
   "The site has versions in several languages and this page does not say so. "
   "Search engines then treat the versions as competitors rather than "
   "alternatives, and may show the wrong one to the wrong country.",
 "hreflang-no-self":
   "An hreflang cluster must include the page it sits on. Without the "
   "self-reference the cluster is invalid, and engines are entitled to ignore "
   "the whole set.",
 "hreflang-no-return":
   "hreflang has to be mutual: if A claims B, B must claim A. A one-sided "
   "declaration is discarded, so the work of adding it earns nothing.",
 "hreflang-bad-code":
   "An alternate with an empty or malformed href is a broken link inside the "
   "signal that is supposed to hold the language versions together.",
 "hreflang-unknown-target":
   "The cluster points at a URL that is not among the pages found. Either a "
   "version was removed and the template still declares it, or the addresses "
   "drifted apart.",
 "hreflang-lang-mismatch":
   "The declared language does not match the language the page is actually "
   "written in. This is the failure that sends a Spanish reader to an English "
   "page and counts as a correct result.",
 "hreflang-canonical-conflict":
   "The canonical points at another language while hreflang says the versions "
   "are equals. The two signals contradict each other, and the engine resolves "
   "the contradiction however it likes.",
 "hreflang-target-blocked":
   "The cluster points at a page that is closed from indexing. The link is "
   "there, the destination cannot be used, and the cluster is weaker for it.",
 "hreflang-static-cluster":
   "Many pages declaring one identical set of alternates means the block was "
   "hard-coded into the template instead of being built per page. It is right "
   "for the page it was copied from and wrong for every other.",

 "no-question-headings":
   "AI search retrieves passages, not pages, and a heading phrased as a "
   "question is the clearest boundary a passage can have. This is the cheapest "
   "structural change with a direct effect on being quoted.",
 "no-answer":
   "If the opening paragraph does not answer the page's own question, there is "
   "nothing on the page that can be lifted as an answer — regardless of how "
   "good the rest is.",
 "answer-short":
   "An answer too short to stand on its own gets quoted without its context and "
   "reads as incomplete wherever it lands.",
 "answer-long":
   "A long opening block does not get quoted whole; it gets cut, and you do not "
   "choose where.",
 "answer-preamble":
   "“In this article we will look at…” is a run-up, not an answer. AI search "
   "quotes the beginning, so the beginning has to be the substance.",
 "jsonld-no-type":
   "A JSON-LD block without @type parses but says nothing: a search engine has "
   "no way to know what the object is meant to describe, so the markup costs "
   "you bytes and returns nothing.",
 "jsonld-broken":
   "Structured data that does not parse does not exist as far as a search "
   "engine is concerned — with the added cost that you believe it is there.",
 "jsonld-faq-invisible":
   "Marking up questions that are not in the visible text is against every "
   "engine's guidelines and is the kind of thing that gets rich results "
   "withdrawn from a whole site.",
 "no-author":
   "An identified author or organisation is the part of E-E-A-T a page can "
   "actually carry. On generated pages it is usually absent for the whole "
   "template at once.",
 "no-date":
   "A machine-readable date is how freshness is judged. Without one the page is "
   "undated, and undated tends to be read as old.",
 "ai-crawler-blocked":
   "The crawlers behind AI answers are blocked in robots.txt. That may well be "
   "deliberate — the point is that it should be a decision, taken knowingly, "
   "rather than a line inherited from a template.",

 "robots-blocks-all":
   "Disallow: / for every agent closes the entire site to every search engine. "
   "It is almost always a staging file that was deployed to production."
   " This is the single most expensive finding in the package, and the easiest to miss: the site keeps building, deploying and passing every other check while earning nothing at all. It is reported once, at site level, because there is exactly one file to fix and reporting it per page would bury it under everything else.",
 "robots-no-sitemap":
   "The Sitemap line in robots.txt is the one place every crawler looks without "
   "being asked. Leaving it out means relying on each engine being told "
   "separately."
   " Submitting a sitemap through each search engine's own panel works, and stops working the moment a new engine matters or an account changes hands. The line in robots.txt is the version that keeps working without anyone remembering it, and it is the only discovery route the crawlers behind AI answers reliably follow.",
 "robots-unreadable":
   "A robots.txt that cannot be read is not a permissive robots.txt — crawler "
   "behaviour in that situation is not something you get to choose."
   " An unreadable robots.txt is treated differently by different crawlers: some assume everything is allowed, others back off entirely. The problem is not which of those you get — it is that you do not get to choose, and the behaviour can differ between engines on the same day.",
 "no-robots":
   "No robots.txt is not an error, but it is an absence of control: crawl rate, "
   "sitemap discovery and AI-crawler policy all default to whatever each engine "
   "prefers."
   " Nothing breaks without robots.txt, which is exactly why it stays missing. What is lost is the ability to say anything at all: crawl rate, the sitemap location, and whether the crawlers behind AI answers are welcome are all decided for you, engine by engine, with no record of the decision anywhere in your repository.",

 "stale-event":
   "A dated event that has passed and is still open for indexing sends people "
   "to something that already happened. Search engines demote it; readers who "
   "arrive are worse off than if they had found nothing.",
 "stale-closed":
   "The page describes something that has ended. Lower stakes than a stale "
   "event, and still a page whose usefulness expired."
   " Expired pages are worth keeping when they carry history, and worth removing when they only carry a promise that is no longer true. indexgap does not decide which — it reports the date it found and leaves the judgement to you, because the same expired page can be an archive on one site and a broken promise on another.",
}

FAMILIES = [
 ("invented-facts", "Invented facts",
  "The checks that compare what a page says against the data row that produced "
  "it. This is the part of the package that has no equivalent in a general site "
  "auditor, and the reason indexgap will not write page text for you: a "
  "generator that supplied the numbers could not then check them.",
  ["unsupported-number", "check-by-eye", "source-note", "still-draft", "brief-left"]),

 ("indexing", "Indexing and reachability",
  "Whether a page can be found, crawled and kept in the index at all. Nothing "
  "further down this list matters on a page that fails here.",
  ["noindex", "nosnippet", "canonical-elsewhere", "orphan", "unreachable", "deep", "js-shell"]),

 ("content", "Content quality at scale",
  "The failures that only appear when pages are compared with each other. A "
  "single generated page always looks fine; it is the set that gives the "
  "pipeline away.",
  ["thin", "low-uniqueness", "template-skeleton", "same-opening",
   "near-duplicate", "similar", "long-paragraph"]),

 ("head", "Titles, descriptions and headings",
  "The fields a search engine reads first and a person sees before deciding to "
  "click. On a generated site each of these is written once, in a template, and "
  "is therefore either right everywhere or wrong everywhere.",
  ["no-title", "title-short", "title-long", "duplicate-title",
   "no-description", "description-length", "duplicate-description",
   "no-h1", "many-h1", "no-headings", "no-structure", "img-no-alt", "vague-anchor"]),

 ("hreflang", "hreflang and language versions",
  "hreflang is mutual, self-inclusive and per-page — three properties a "
  "template gets wrong in three different ways. These checks validate the "
  "cluster as a whole rather than the tag in isolation.",
  ["hreflang-missing", "hreflang-no-self", "hreflang-no-return", "hreflang-bad-code",
   "hreflang-unknown-target", "hreflang-lang-mismatch", "hreflang-canonical-conflict",
   "hreflang-target-blocked", "hreflang-static-cluster"]),

 ("aeo", "AI search and answer extraction",
  "AI search retrieves passages and quotes them. These checks ask whether a "
  "page contains anything that survives being lifted out of it.",
  ["no-question-headings", "no-answer", "answer-short", "answer-long",
   "answer-preamble", "jsonld-broken", "jsonld-no-type", "jsonld-faq-invisible",
   "no-author", "no-date", "ai-crawler-blocked"]),

 ("robots", "robots.txt",
  "Site-level findings: one file, one fix, reported once rather than per page.",
  ["robots-blocks-all", "robots-no-sitemap", "robots-unreadable", "no-robots"]),

 ("freshness", "Freshness",
  "Pages whose usefulness has an expiry date, still open for indexing after it "
  "passed.",
  ["stale-event", "stale-closed"]),
]

COMMANDS = [
 ("init", "Read the project and record what makes it different",
  "Works out where the pages are, the site URL, the content type and the "
  "dataset, writes indexgap.json, installs the agent skills into .claude/skills/ "
  "and adds the working files to .gitignore. Run once per project."),
 ("plan", "Audit the dataset before a single page is generated",
  "Reads the keyword file, finds duplicates and near-synonyms that would become "
  "competing pages, checks that the path pattern resolves for every row, and "
  "writes the work list. The cheapest place to fix a pipeline is before it runs."),
 ("check", "The full audit of generated pages",
  "Every check in this reference, run against the pages on disk or a live site: "
  "invented numbers, indexing, duplicates, hreflang clusters, headings and "
  "structured data. Reports HTML and JSON."),
 ("brief", "Turn findings into work orders",
  "Lays the findings out as markdown files next to the pages they belong to, "
  "with an imperative fix, the thresholds the result must meet, and the dataset "
  "row as the only permitted source of numbers. Writes no page text, "
  "deliberately."),
 ("sitemap", "Build a sitemap from what actually exists",
  "Generates the sitemap from the pages found, not from the dataset — so a page "
  "that failed to generate does not get announced to search engines as though "
  "it had."),
 ("notify", "Push new and changed URLs to IndexNow",
  "Submits only what changed since the last run, using the manifest, so a "
  "thousand-page site does not resubmit itself daily."),
 ("portfolio", "One table across every project",
  "Runs the audit over several sites at once and reports them side by side, "
  "so that a portfolio of generated sites can be triaged in one pass instead of "
  "one project at a time. Each row carries the same counts a single audit "
  "produces — critical findings, warnings, duplicate clusters, orphans — which "
  "makes the comparison meaningful rather than decorative: the site with three "
  "hundred warnings and no critical findings is in better shape than the one "
  "with two criticals, and the table says so at a glance. Projects are read "
  "from their own indexgap.json files, so each keeps its own thresholds and "
  "content profile; a catalogue and a blog are not forced onto one standard "
  "just because they are reported together."),
 ("profiles", "Show the built-in content profiles",
  "Thresholds differ by content type: a reference page and a landing page are "
  "not thin at the same word count, and an events site has a notion of "
  "staleness that a product catalogue does not. Profiles are the named sets of "
  "thresholds that encode those differences — catalog, events, ugc, product — "
  "and choosing one changes both the numbers and which checks run at all. "
  "Every value in a profile can be overridden per project in indexgap.json, "
  "which is the intended way to disagree with a threshold: change the number "
  "that is being checked against, rather than padding pages until they clear a "
  "bar you did not choose. The command prints each profile with its actual "
  "values, so the disagreement can be an informed one."),
 ("doctor", "The crawl-to-index funnel",
  "Follows the pages from what was generated, through the sitemap, to what each "
  "search engine has actually indexed — and reports where they were lost."),
 ("cite", "Measure whether AI search cites you",
  "Asks Perplexity, the OpenAI Responses API, Gemini and Grok a set of real "
  "user questions and counts how often your domain comes back among the "
  "sources. The only command that needs API keys, and it sends nothing without "
  "an explicit flag."),
]


# ── шаблон ───────────────────────────────────────────────────────────────────

CSS = """
:root{--paper:#f7f8f8;--card:#fff;--soft:#eceff0;--ink:#151c1e;--ink2:#42504f;
--ink3:#70807e;--rule:#d6dedd;--acc:#0d6b60;--accbg:#dbebe8;
--crit:#9c3a25;--critbg:#f5ded8;--warn:#8a5410;--warnbg:#f3e7d2;--info:#3a5f7a;--infobg:#dee8ef;
--mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){
--paper:#0f1615;--card:#161e1d;--soft:#1c2625;--ink:#e2eae8;--ink2:#a6b4b1;
--ink3:#798683;--rule:#283432;--acc:#53c2ad;--accbg:#15322c;
--crit:#e28b72;--critbg:#37211b;--warn:#d9a463;--warnbg:#32271a;--info:#8fb6cf;--infobg:#1b2831;}}
:root[data-theme=dark]{
--paper:#0f1615;--card:#161e1d;--soft:#1c2625;--ink:#e2eae8;--ink2:#a6b4b1;
--ink3:#798683;--rule:#283432;--acc:#53c2ad;--accbg:#15322c;
--crit:#e28b72;--critbg:#37211b;--warn:#d9a463;--warnbg:#32271a;--info:#8fb6cf;--infobg:#1b2831;}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
font-size:17px;line-height:1.62;-webkit-font-smoothing:antialiased}
.wrap{max-width:52rem;margin:0 auto;padding:2rem 1.25rem 5rem}
a{color:var(--acc)}
a:focus-visible{outline:2px solid var(--acc);outline-offset:2px;border-radius:2px}
nav.top{display:flex;gap:1.1rem;flex-wrap:wrap;font-size:.86rem;padding-bottom:1.1rem;
margin-bottom:2rem;border-bottom:1px solid var(--rule)}
nav.top a{text-decoration:none;color:var(--ink2)}
nav.top a:hover{color:var(--acc)}
nav.top .brand{font-family:var(--mono);font-weight:600;color:var(--ink)}
h1{font-size:2.05rem;line-height:1.15;letter-spacing:-.02em;margin:.2rem 0 .6rem;text-wrap:balance}
h2{font-size:1.28rem;letter-spacing:-.01em;margin:2.4rem 0 .7rem}
h3{font-size:1.03rem;margin:1.7rem 0 .4rem}
p{margin:.75rem 0}
.lede{font-size:1.1rem;color:var(--ink2);margin-bottom:1.6rem}
code{font-family:var(--mono);font-size:.87em;background:var(--soft);padding:.12em .38em;border-radius:3px}
pre{background:var(--soft);padding:.9rem 1rem;border-radius:6px;overflow-x:auto;font-size:.86rem}
pre code{background:none;padding:0}
.tag{display:inline-block;font-family:var(--mono);font-size:.7rem;text-transform:uppercase;
letter-spacing:.07em;padding:.16rem .45rem;border-radius:3px;background:var(--soft);color:var(--ink3)}
.tag.critical{background:var(--critbg);color:var(--crit)}
.tag.warning{background:var(--warnbg);color:var(--warn)}
.tag.info{background:var(--infobg);color:var(--info)}
.tag.acc{background:var(--accbg);color:var(--acc)}
.meta{display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:1.3rem}
.card{background:var(--card);border:1px solid var(--rule);border-radius:7px;padding:1rem 1.15rem;margin:1rem 0}
.card h3{margin-top:0}
.fix{border-left:3px solid var(--acc);background:var(--accbg);padding:.85rem 1.05rem;border-radius:0 6px 6px 0;margin:1rem 0}
table{width:100%;border-collapse:collapse;font-size:.92rem;margin:1rem 0}
th,td{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-family:var(--mono);font-size:.72rem;text-transform:uppercase;letter-spacing:.07em;color:var(--ink3)}
.scroll{overflow-x:auto}
ul.plain{list-style:none;padding:0;margin:1rem 0;display:grid;gap:.5rem}
ul.plain li{display:flex;gap:.7rem;align-items:baseline}
ul.plain a{font-family:var(--mono);font-size:.88rem;text-decoration:none;flex:none}
ul.plain span{color:var(--ink2);font-size:.9rem}
footer{margin-top:4rem;padding-top:1.2rem;border-top:1px solid var(--rule);
font-size:.85rem;color:var(--ink3)}
"""


def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def page(path: str, title: str, description: str, body: str,
         crumbs: str = "") -> None:
    """Одна страница: свой title, свой description, canonical на себя."""
    depth = path.count("/")
    up = "../" * depth
    url = f"{SITE}/{path}"
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{html.escape(description, quote=True)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="article">
<meta property="og:title" content="{html.escape(title, quote=True)}">
<meta property="og:description" content="{html.escape(description, quote=True)}">
<meta property="og:url" content="{url}">
<meta name="author" content="{AUTHOR}">
<script type="application/ld+json">{{
 "@context":"https://schema.org","@type":"TechArticle",
 "headline":{json.dumps(title)},"description":{json.dumps(description)},
 "url":{json.dumps(url)},"inLanguage":"en",
 "datePublished":"{PUBLISHED}","dateModified":"{PUBLISHED}",
 "author":{{"@type":"Person","name":"{AUTHOR}"}},
 "publisher":{{"@type":"Organization","name":"indexgap"}},
 "isPartOf":{{"@type":"WebSite","name":"indexgap","url":{json.dumps(SITE)}}}
}}</script>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<nav class="top">
  <a class="brand" href="{up}index.html">indexgap</a>
  <a href="{up}checks/index.html">Checks</a>
  <a href="{up}commands/index.html">Commands</a>
  <a href="{REPO}">GitHub</a>
</nav>
{crumbs}
{body}
<footer>
  <p>By {AUTHOR}. Published <time datetime="{PUBLISHED}">29 August 2026</time>,
  for indexgap {esc(__version__)}.</p>
  <p>indexgap {esc(__version__)} — quality control for programmatic SEO pipelines.
  Python 3.9+, standard library only. MIT.
  <a href="{REPO}">Source on GitHub</a>.</p>
  <p>This site is generated from the package's own check registry by
  <code>tools/build_docs.py</code>, so it cannot drift from the code it documents.</p>
</footer>
</div>
</body>
</html>
"""
    target = OUT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(doc, encoding="utf-8")


def collect() -> dict:
    """Реестр проверок из пакета: уровень и текст находки — из исходников."""
    src = "".join(p.read_text(encoding="utf-8")
                  for p in (ROOT / "indexgap").glob("*.py"))
    # находка — это кортеж (уровень, что, код, tr(текст)); собирается он
    # и через issues.append, и через return [...], поэтому привязки к append нет
    pat = re.compile(
        r'\(\s*"(critical|warning|info)"\s*,\s*[^,\n]+,\s*'
        r'"([a-z0-9-]+)"\s*,\s*\n?\s*tr\(\s*"((?:[^"\\]|\\.)*)"', re.S)
    seen = {}
    for level, code, message in pat.findall(src):
        seen.setdefault(code, (level, message))

    # объединение: часть проверок эмитится, но не имеет записи в FIX
    codes = set(repair.FIX) | set(seen) | set(checks.CODE_WEIGHT)
    codes -= {"noindex-meta"}
    out = {}
    for code in sorted(codes):
        level, message = seen.get(code, ("", ""))
        out[code] = {
            "level": level,
            "message": re.sub(r"\{a\d\}", "…", message).strip(),
            "fix": repair._fix(code),
            "template_wide": code not in checks.NOT_TEMPLATE_WIDE,
            "grouped": code in repair.GROUPED,
            "site_level": code in repair.SITE_LEVEL,
            "shell_dependent": code in checks.SHELL_DEPENDENT,
        }
    return out


def humanise(code: str) -> str:
    return code.replace("-", " ")


def check_page(code: str, data: dict, family: tuple, siblings: list) -> None:
    level = data["level"] or "info"
    why = WHY.get(code, "")
    fam_slug, fam_title = family[0], family[1]

    behaviour = []
    if data["site_level"]:
        behaviour.append(
            "This is a <b>site-level</b> finding: it belongs to the site, not to "
            "any one page, and is reported once however many pages are audited.")
    if data["grouped"]:
        behaviour.append(
            "Fixed as a <b>group</b>. A single page out of a duplicate cluster "
            "cannot be fixed alone, so <code>indexgap brief</code> writes one "
            "work order per cluster rather than one per page.")
    if data["template_wide"] and not data["site_level"]:
        behaviour.append(
            "Collapsed when it fires <b>template-wide</b>. If it appears on 90% "
            "or more of the pages — or of one language version — it is a "
            "property of the template and is reported once, with the count, "
            "instead of once per page.")
    else:
        if not data["site_level"] and not data["grouped"]:
            behaviour.append(
                "Reported <b>per page</b> even when it is common. Appearing on "
                "many pages is the nature of this finding rather than evidence "
                "of one template defect, so collapsing it would hide real work.")
    if data["shell_dependent"]:
        behaviour.append(
            "Suppressed on JavaScript shells. A page with no text in its source "
            "HTML would trip this check for a reason that is already reported as "
            "<code>js-shell</code>, and repeating it four times is not four times "
            "as informative.")

    if data["fix"]:
        fix_block = ("<h2>How to fix it</h2>"
                     f'<div class="fix"><p>{esc(data["fix"])}</p></div>')
    else:
        fix_block = (
            "<h2>How to fix it</h2><p>The package does not yet ship an "
            "imperative fix for this finding, so <code>indexgap brief</code> "
            "reports it without one. The finding itself still tells you what "
            "was seen.</p>")

    others = "".join(
        f'<li><a href="{c}.html">{esc(c)}</a><span>{esc(humanise(c))}</span></li>'
        for c in siblings if c != code)

    body = f"""
<h1>{esc(humanise(code))}</h1>
<div class="meta">
  <span class="tag {level}">{esc(level)}</span>
  <span class="tag">{esc(code)}</span>
  <span class="tag acc">{esc(fam_title)}</span>
</div>
<p class="lede">{why}</p>

<h2>What indexgap reports</h2>
<p>The finding reads:</p>
<pre><code>{esc(level)}  {esc(code)}  {esc(data['message'] or '—')}</code></pre>

{fix_block}

<h2>How it behaves at scale</h2>
{''.join(f'<p>{b}</p>' for b in behaviour)}

<h2>Finding it</h2>
<pre><code>pipx install indexgap
cd your-project
indexgap init
indexgap check</code></pre>
<p>Then <a href="../commands/brief.html"><code>indexgap brief</code></a> turns
every finding on this page into a work order placed next to the page it belongs
to, with the thresholds the result has to satisfy.</p>

<h2>Related checks in {esc(fam_title.lower())}</h2>
<ul class="plain">{others}</ul>
<p><a href="index.html">All checks</a> · <a href="index.html#{fam_slug}">{esc(fam_title)}</a></p>
"""
    desc = (f"{humanise(code)}: what indexgap reports, why it matters and how to "
            f"fix it. Reported as {level}.")
    page(f"checks/{code}.html", f"{humanise(code)} — indexgap check", desc, body)


def build() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    data = collect()
    known = {c for f in FAMILIES for c in f[3]}
    missing = set(data) - known
    if missing:
        raise SystemExit(f"проверки без семейства: {sorted(missing)}")
    unknown = known - set(data)
    if unknown:
        raise SystemExit(f"семейство ссылается на несуществующие коды: {sorted(unknown)}")
    no_why = [c for c in data if not WHY.get(c)]
    if no_why:
        raise SystemExit(f"проверки без текста WHY: {no_why}")

    # ── страницы проверок ────────────────────────────────────────────────
    for family in FAMILIES:
        for code in family[3]:
            check_page(code, data[code], family, family[3])

    # ── каталог проверок ─────────────────────────────────────────────────
    counts = {"critical": 0, "warning": 0, "info": 0}
    for v in data.values():
        if v["level"]:
            counts[v["level"]] += 1

    sections = []
    for slug, title, intro, codes in FAMILIES:
        rows = "".join(
            f'<tr><td><a href="{c}.html"><code>{esc(c)}</code></a></td>'
            f'<td><span class="tag {data[c]["level"] or "info"}">'
            f'{esc(data[c]["level"] or "info")}</span></td>'
            f'<td>{esc(data[c]["message"] or humanise(c))}</td></tr>'
            for c in codes)
        sections.append(
            f'<h2 id="{slug}">{esc(title)}</h2><p>{intro}</p>'
            f'<div class="scroll"><table><thead><tr><th>Check</th><th>Level</th>'
            f'<th>What it reports</th></tr></thead><tbody>{rows}</tbody></table></div>')

    body = f"""
<h1>Every check indexgap runs</h1>
<p class="lede">{len(data)} checks across {len(FAMILIES)} families —
{counts['critical']} critical, {counts['warning']} warning, {counts['info']} info.
Each has its own page: what triggers it, why it is worth fixing, and the
imperative fix the package hands to a person or an agent.</p>
<p>The list is generated from the package's own registry at build time, so it is
the same set of checks the installed version runs — not a description of them.</p>
{''.join(sections)}
"""
    page("checks/index.html", "Every check indexgap runs",
         f"Reference for all {len(data)} checks in indexgap: level, trigger and fix "
         "for invented numbers, indexing, duplicates, hreflang and AI-search readiness.",
         body)

    # ── страницы команд ──────────────────────────────────────────────────
    helps = {}
    for name, _, _ in COMMANDS:
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                cli.main([name, "--help"])
        except SystemExit:
            pass
        helps[name] = buf.getvalue().strip()

    for i, (name, summary, detail) in enumerate(COMMANDS):
        nav = []
        if i:
            nav.append(f'<a href="{COMMANDS[i-1][0]}.html">← {COMMANDS[i-1][0]}</a>')
        if i + 1 < len(COMMANDS):
            nav.append(f'<a href="{COMMANDS[i+1][0]}.html">{COMMANDS[i+1][0]} →</a>')
        body = f"""
<h1>indexgap {esc(name)}</h1>
<div class="meta"><span class="tag acc">command</span></div>
<p class="lede">{esc(summary)}.</p>
<p>{esc(detail)}</p>
<h2>Usage</h2>
<pre><code>{esc(helps[name])}</code></pre>
<h2>The rest of the pipeline</h2>
<ul class="plain">{''.join(
   f'<li><a href="{n}.html">{esc(n)}</a><span>{esc(s)}</span></li>'
   for n, s, _ in COMMANDS if n != name)}</ul>
<p>{' · '.join(nav)}</p>
"""
        page(f"commands/{name}.html", f"indexgap {name} — {summary.lower()}",
             f"{summary}. Usage, flags and where {name} sits in the indexgap pipeline.",
             body)

    rows = "".join(
        f'<tr><td><a href="{n}.html"><code>indexgap {esc(n)}</code></a></td>'
        f'<td>{esc(s)}</td></tr>' for n, s, _ in COMMANDS)
    page("commands/index.html", "The ten indexgap commands",
         "What each indexgap command does and where it sits in the pipeline, from "
         "auditing the dataset to measuring citations in AI search.",
         f"""
<h1>The ten commands</h1>
<p class="lede">The pipeline runs in the order the pages do: audit the dataset
before generating, audit the pages after, turn the findings into work orders,
then publish and measure.</p>
<p>The order matters more than it looks. Most of what goes wrong with a
generated site is decided before a single page exists — two keywords with the
same intent become two pages competing with each other, and no amount of
auditing afterwards makes them one page again. That is what
<a href="plan.html"><code>plan</code></a> is for, and it is the cheapest command
in the set to run.</p>
<p>Everything after it assumes pages already exist.
<a href="check.html"><code>check</code></a> is the full audit,
<a href="brief.html"><code>brief</code></a> turns its findings into work orders a
person or an agent can pick up, and
<a href="doctor.html"><code>doctor</code></a> follows the pages through the
sitemap to what search engines actually indexed — the step that answers why
correct pages still earn nothing.</p>
<div class="scroll"><table><thead><tr><th>Command</th><th>What it does</th></tr>
</thead><tbody>{rows}</tbody></table></div>
""")

    # ── главная ──────────────────────────────────────────────────────────
    fam_list = "".join(
        f'<li><a href="checks/index.html#{slug}">{esc(title)}</a>'
        f'<span>{len(codes)} checks</span></li>'
        for slug, title, _, codes in FAMILIES)

    page("index.html",
         "indexgap — quality control for programmatic SEO",
         "Open-source CLI that audits programmatic SEO pipelines: invented numbers "
         "checked against the source dataset, template-wide breakage, near-duplicate "
         "clustering and hreflang validation. Python, no dependencies.",
         f"""
<h1>Quality control for programmatic SEO pipelines</h1>
<p class="lede">You generated three thousand pages from a dataset. They are on
disk, they are in the sitemap, and there is no traffic. indexgap tells you where
they were lost — and which of the numbers on those pages your generator
invented.</p>

<pre><code>pipx install indexgap
cd your-project
indexgap init
indexgap check</code></pre>

<h2>The check that has no equivalent elsewhere</h2>
<p>Every general site auditor will tell you a page is thin or a title is
duplicated. None of them can tell you that a visa page states a processing time
that appears nowhere in the row of data that produced it. indexgap compares the
numbers printed on each page against its own dataset row, and that is the check
the rest of the package is built around.</p>
<p>It is also why <b>indexgap never writes page text</b>. If the package supplied
those numbers itself, the check would be checking its own output and would be
green forever.</p>

<h2>What it looks for</h2>
<ul class="plain">{fam_list}</ul>
<p><a href="checks/index.html">All {len(data)} checks →</a></p>

<h2>Findings are not tasks</h2>
<p>On a live 2,970-page catalogue the audit reports 6,074 findings.
<a href="commands/brief.html"><code>indexgap brief</code></a> turns them into 966
work orders — because a finding that fires on nearly every page is one template
defect, and a near-duplicate cluster of 24 pages is one decision, not 24.</p>

<h2>Ten commands</h2>
<p>From auditing the keyword file before a single page exists, through the audit
itself, to the crawl-to-index funnel and measuring whether AI search cites you.
<a href="commands/index.html">See all ten →</a></p>

<h2>What it costs to run</h2>
<p>Python 3.9 and up, standard library only. No dependencies, no API keys, no
telemetry, no account. Nothing leaves your machine without an explicit flag. The
one command that queries AI search engines needs your own keys and sends nothing
without <code>--send</code>. MIT licensed.</p>
""")

    # ── robots.txt и sitemap.xml ─────────────────────────────────────────
    urls = sorted(str(p.relative_to(OUT)).replace(os.sep, "/")
                  for p in OUT.rglob("*.html"))
    entries = "".join(
        f"  <url><loc>{SITE}/{u}</loc></url>\n" for u in urls)
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}</urlset>\n", encoding="utf-8")
    (OUT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n", encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    print(f"страниц: {len(urls)}  проверок: {len(data)}  команд: {len(COMMANDS)}")


if __name__ == "__main__":
    build()
