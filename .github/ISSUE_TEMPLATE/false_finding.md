---
name: A finding that is wrong
about: indexgap reported something that isn't true, or missed something that is
title: ''
labels: ''
assignees: ''
---

**Which finding code**
For example `orphan`, `near-duplicate`, `js-shell`. It is the short word in the
"чинить в этом порядке" list and in the report.

**What indexgap said**

```
paste the command you ran and the lines it printed
```

**What is actually true**
What you see on the page or in Search Console that contradicts it.

**A page that shows it**
The smallest HTML or Markdown file that reproduces the finding, if you can
share one. A public URL works too.

**Version**

```
python3 -c "import indexgap; print(indexgap.__version__)"
python3 --version
```

---

A wrong finding is worth more than a feature request here: every check in this
package exists because something was found broken, and each one is pinned by a
test. If yours is real, it becomes a test.
