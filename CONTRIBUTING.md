# Contributing

Thanks for looking. Three rules keep this package what it is.

## 1. No dependencies

`indexgap` runs on the Python 3.9+ standard library and nothing else. Not as a
badge — as a working constraint. Its audience includes people who do not
program, on machines where `pip install` of a compiled wheel fails. XLSX is
read with `zipfile` for exactly this reason.

If a change needs a library, it needs a different design.

## 2. A finding without a test comes back

Every check in this package exists because something was found broken, and
every one of those has a test that reproduces the original defect. `tests/`
is organised by where the defects came from:

| File | What is pinned there |
|---|---|
| `test_regressions.py` | first adversarial review wave |
| `test_wave2.py` | second wave — including regressions the first wave's repairs introduced |
| `test_portfolio.py` | portfolio mode and content-type profiles |
| `test_install.py` | `indexgap init`, and that no IndexNow key is ever copied |
| `test_live.py` | defects found only by running against six production sites |
| `test_sources.py` | exports from tools other than webmaster panels |

Run them with:

```bash
python3 -m unittest discover -s tests
```

A pull request that changes behaviour and adds no test will be asked for one.
Write the test so it fails before your change.

## 3. Never answer confidently when you don't know

This is the rule the package was rebuilt around, and it is worth stating
plainly because it is easy to violate while writing correct code.

* A check that fires on every page is not a list of things to fix — it is a
  property of the template, and must be reported as one.
* Two exports that cannot be told apart get the answer "I don't know", not a
  guessed label. A wrong label merges two indexes into one and silently
  destroys the comparison the report exists for.
* A crawler export is not proof of indexation. If the number in a funnel step
  came from something that isn't an index, the step says so.
* A threshold is a policy, not a discovery. Where the underlying distribution
  is continuous, say that out loud instead of implying a natural boundary.

Silence is a finding too: when a check could not run, the report states why
rather than leaving an empty section that reads like a clean bill of health.

## Style

Russian docstrings and comments, matching the existing files — they explain
*why*, not *what*, and several encode a defect that would otherwise return.
Code identifiers and log-level plumbing stay in English. Keep
`from __future__ import annotations` at the top of every module.

Before opening a pull request:

```bash
python3 -m unittest discover -s tests
python3 -m indexgap --help
```

CI runs the same on Python 3.9, 3.11 and 3.13.
