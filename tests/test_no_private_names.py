# -*- coding: utf-8 -*-
"""
Сайты владельцев, на которых калибруются проверки, не называются публично.

Проверки улучшаются на живых проектах, но в библиотеку попадает только то,
что пригодится любому сайту: правило, тест и обезличенный пример. Название,
домен и узнаваемые детали чужого (или своего непубличного) проекта в коде,
тестах, документации и CHANGELOG — утечка.

Имена здесь хранятся только как SHA-256: тест не должен сам их публиковать.
Чтобы добавить имя, положи в BANNED хеш `sha256(имя.lower())`.
"""

import hashlib
import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent

BANNED = {
    "00c74249eb8906a2b5b6bc1c9817ba9ef50ed48aa68726e478093e6258eaf720",
    "c70caf94a3e5cc8a3ac90e8de536efe8468bb360cf821b8f8476d86a28e8e86e",
    "992715132a04e51080125ac51ec2fb467d8015144120780ce12af6e3468e9bce",
    "e07eb26366ada4d198ee596d888051d278bcbeb94d937b02b40bf20c1f951d85",
    "a7b45e3480ac9567d3c73057e81d095a9fda01ecc6bf2cf1f0dda473f2e1a81f",
    "9cb7914bc58d2904023f574b91a37831123caa3aa6844f734dc20c1c659274a6",
    "4bcec06afde340f28366de82a87d14bde6daf87418545b0f594e77001a67fbee",
    "587cce51ddb48234f5cdc1e342bd5ad5dc663fc516faf8c7770349f9aeb170fc",
}

# Слово, слово с доменом и составное имя файла: `name`, `name.app`, `name-x`.
_TOKEN = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")


def _tracked():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        out = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file()
               and ".git" not in p.parts]
    return [ROOT / f for f in out if not f.startswith("build/")]


def _variants(token):
    """Сам токен и его части: `x.app` → `x.app`, `x`, `app`; `a-b.io` → … `a`, `b`."""
    yield token
    for part in re.split(r"[.-]", token):
        yield part
    pieces = token.split(".")
    for i in range(1, len(pieces)):
        yield ".".join(pieces[:i + 1])


class TestNoPrivateNames(unittest.TestCase):
    def test_owner_projects_are_not_named(self):
        found = []
        for path in _tracked():
            if path.suffix in {".png", ".jpg", ".zip", ".gz", ".ico", ".pdf", ".whl"}:
                continue
            try:
                text = path.read_text(encoding="utf-8").lower()
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                for token in _TOKEN.findall(line):
                    if any(hashlib.sha256(v.encode()).hexdigest() in BANNED
                           for v in _variants(token)):
                        found.append(f"{path.relative_to(ROOT)}:{number}")
                        break
        self.assertEqual(found, [], "в публичных файлах названы проекты владельца: "
                                    + ", ".join(found[:10]))


if __name__ == "__main__":
    unittest.main()
