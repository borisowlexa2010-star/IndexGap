# -*- coding: utf-8 -*-
"""
Скрипт шага GitHub Action — тем же bash, каким его запустит раннер.

Задание CI `action` гоняет действие целиком, но только на GitHub. Здесь —
тот же текст шага из action.yml с подставными GITHUB_OUTPUT, RUNNER_TEMP
и `indexgap` из этого репозитория: код возврата из двух строгих прогонов,
выходы и сводка проверяются при каждом `unittest`.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language  # noqa: F401  — закрепляет русский язык вывода

from indexgap import cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo-site")
SITE = "https://demo.example"


def step_script(step_id: str = "check") -> str:
    """Текст `run: |` шага с данным id — без разбора YAML, по отступам."""
    with open(os.path.join(ROOT, "action.yml"), encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    start = next(n for n, line in enumerate(lines) if line.strip() == f"id: {step_id}")
    run = next(n for n in range(start, len(lines)) if lines[n].strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip()) + 2
    body = []
    for line in lines[run + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:])
    return "\n".join(body) + "\n"


def action_text() -> str:
    with open(os.path.join(ROOT, "action.yml"), encoding="utf-8") as fh:
        return fh.read()


class ActionText(unittest.TestCase):
    def test_inputs_and_outputs_for_diff_are_declared(self):
        text = action_text()
        self.assertIn("\n  old-root:\n", text)
        self.assertIn("\n  diff-args:\n", text)
        self.assertIn("${{ steps.check.outputs.diff-data }}", text)
        self.assertIn("${{ steps.check.outputs.diff-report }}", text)

    def test_the_script_takes_inputs_only_from_the_environment(self):
        # `${{ }}` внутри скрипта — подстановка до bash: кавычка во входе
        # становится кодом. Входы приходят только через env.
        self.assertNotIn("${{", step_script())
        self.assertIn("IG_OLD_ROOT: ${{ inputs.old-root }}", action_text())


@unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "нужен bash")
class ActionScript(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="indexgap-action-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        bin_dir = os.path.join(self.dir, "bin")
        os.makedirs(bin_dir)
        for name, body in (("indexgap", f'exec "{sys.executable}" -m indexgap "$@"\n'),
                           ("python", f'exec "{sys.executable}" "$@"\n')):
            path = os.path.join(bin_dir, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("#!/bin/sh\n" + body)
            os.chmod(path, 0o755)
        self.bin = bin_dir
        self.script = os.path.join(self.dir, "step.sh")
        with open(self.script, "w", encoding="utf-8") as fh:
            fh.write(step_script())
        self.runner_temp = os.path.join(self.dir, "runner")
        os.makedirs(self.runner_temp)

        # Старая сборка: демо-сайт и ещё одна открытая страница, которой в новой нет.
        self.old_more = os.path.join(self.dir, "old-more")
        shutil.copytree(DEMO, self.old_more)
        os.makedirs(os.path.join(self.old_more, "rent", "bonn"))
        shutil.copy(os.path.join(DEMO, "rent", "berlin", "index.html"),
                    os.path.join(self.old_more, "rent", "bonn", "index.html"))
        self.old_same = os.path.join(self.dir, "old-same")
        shutil.copytree(DEMO, self.old_same)

        out = os.path.join(self.dir, "base", "indexgap-check.html")
        os.makedirs(os.path.dirname(out))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["check", DEMO, "--site", SITE, "--out", out])
        self.baseline = out[:-5] + ".json"

    def run_step(self, **inputs):
        output = os.path.join(self.dir, "github_output")
        summary = os.path.join(self.dir, "step_summary")
        for path in (output, summary):
            open(path, "w").close()
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ.get("PATH", ""),
                   PYTHONPATH=ROOT, INDEXGAP_LANG="en", PYTHONUTF8="1",
                   RUNNER_TEMP=self.runner_temp, GITHUB_OUTPUT=output,
                   GITHUB_STEP_SUMMARY=summary)
        for key in ("root", "site", "baseline", "args", "old-root", "diff-args"):
            env["IG_" + key.upper().replace("-", "_")] = inputs.get(key, "")
        env["IG_STRICT"] = inputs.get("strict", "true")
        proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", self.script],
                              env=env, cwd=self.dir, capture_output=True, text=True,
                              encoding="utf-8")
        outputs = {}
        with open(output, encoding="utf-8") as fh:
            for line in fh:
                if "=" in line:
                    key, value = line.rstrip("\n").split("=", 1)
                    outputs[key] = value
        with open(summary, encoding="utf-8") as fh:
            return proc, outputs, fh.read()

    def test_without_old_root_nothing_changes(self):
        proc, out, summary = self.run_step(root=DEMO, site=SITE, baseline=self.baseline)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(out["code"], "0")
        self.assertEqual(out.get("diff-data", ""), "")
        self.assertNotIn("indexgap diff", summary)

    def test_a_lost_page_fails_the_step_even_when_check_passes(self):
        proc, out, summary = self.run_step(root=DEMO, site=SITE, baseline=self.baseline,
                                           **{"old-root": self.old_more})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(out["code"], "1")
        self.assertTrue(out["diff-data"].startswith(out["dir"]))
        self.assertTrue(os.path.isfile(out["diff-report"]))
        with open(out["diff-data"], encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn(("page-removed", SITE + "/rent/bonn/"),
                      [(i["code"], i["url"]) for i in data["items"]])
        # Обе сводки — и check, и diff — на странице прогона.
        self.assertIn("### indexgap: ", summary)
        self.assertIn("### indexgap diff: ", summary)
        self.assertIn("/rent/bonn/", summary)

    def test_without_strict_the_diff_does_not_fail(self):
        _, out, _ = self.run_step(root=DEMO, site=SITE, strict="false",
                                  **{"old-root": self.old_more})
        self.assertEqual(out["code"], "0")

    def test_an_identical_old_build_passes(self):
        _, out, summary = self.run_step(root=DEMO, site=SITE, baseline=self.baseline,
                                        **{"old-root": self.old_same})
        self.assertEqual(out["code"], "0")
        self.assertIn("### indexgap diff: ", summary)

    def test_a_failing_check_is_not_hidden_by_a_passing_diff(self):
        _, out, _ = self.run_step(root=DEMO, site=SITE, **{"old-root": self.old_same})
        self.assertEqual(out["code"], "1")

    def test_diff_args_reach_the_diff(self):
        _, out, _ = self.run_step(
            root=DEMO, site=SITE, baseline=self.baseline, strict="false",
            **{"old-root": self.old_same,
               "diff-args": f"--dataset '{os.path.join(DEMO, 'cities.csv')}'"})
        with open(out["diff-data"], encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["dataset"], os.path.join(DEMO, "cities.csv"))

    def test_old_root_without_root_is_an_error(self):
        proc, out, _ = self.run_step(site=SITE, **{"old-root": self.old_same})
        self.assertEqual(proc.returncode, 2)
        self.assertIn("old-root", proc.stdout)

    def test_old_root_takes_the_new_build_from_indexgap_json(self):
        with open(os.path.join(self.dir, "indexgap.json"), "w", encoding="utf-8") as fh:
            json.dump({"root": DEMO, "site": SITE}, fh)
        self.addCleanup(os.remove, os.path.join(self.dir, "indexgap.json"))
        proc, out, _ = self.run_step(site=SITE, strict="false",
                                     **{"old-root": self.old_same})
        self.assertNotEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertTrue(out.get("diff-data"), proc.stdout)

    def test_an_unbalanced_quote_in_diff_args_is_an_error(self):
        proc, _, _ = self.run_step(root=DEMO, site=SITE, **{"old-root": self.old_same,
                                                           "diff-args": "--dataset 'x"})
        self.assertEqual(proc.returncode, 2)
        self.assertIn("diff-args", proc.stdout)


if __name__ == "__main__":
    unittest.main()
