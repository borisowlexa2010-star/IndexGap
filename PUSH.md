# Как выложить это на GitHub

Репозиторий уже собран: ветка `main`, история, тег `v1.0.0`, CI.
Осталось создать пустой публичный репозиторий и отправить туда всё.

## Вариант 1 — через gh (быстрее всего)

```bash
cd indexgap
gh repo create indexgap --public --source=. --remote=origin --push \
  --description "Lint your programmatic SEO pipeline — from keywords to indexed pages. Pure Python stdlib, no dependencies, no API keys."
git push origin --tags
```

## Вариант 2 — вручную

1. На https://github.com/new создать репозиторий `indexgap`, **Public**,
   без README, без .gitignore, без лицензии — всё это уже здесь,
   иначе будет конфликт при первом push.
2. Затем:

```bash
cd indexgap
git remote add origin https://github.com/borisowlexa2010-star/indexgap.git
git push -u origin main
git push origin --tags
```

## Сразу после первого push

**Темы** — Settings → About → Topics:

```
seo  programmatic-seo  sitemap  indexnow  aeo  geo  search-console
python  cli  no-dependencies  site-audit
```

**Описание** — там же, одной строкой:

> Lint your programmatic SEO pipeline — from keywords to indexed pages.
> Pure Python stdlib, no dependencies, no API keys.

**Проверить, что CI позеленел.** `.github/workflows/tests.yml` гоняет
217 тестов на Python 3.9, 3.11 и 3.13 и проверяет, что все восемь команд
запускаются. Значок можно вынести в README:

```markdown
![tests](https://github.com/borisowlexa2010-star/indexgap/actions/workflows/tests.yml/badge.svg)
```

**Создать релиз** из тега `v1.0.0` — Releases → Draft a new release →
выбрать тег → «Generate release notes» или скопировать раздел 1.0.0
из `CHANGELOG.md`.

## Публикация в PyPI

Имя `indexgap` на PyPI свободно. Всё уже готово: `.github/workflows/publish.yml`
собирает пакет по тегу `v*`, сверяет тег с версией в коде, прогоняет тесты
и публикует. Токены хранить не нужно — используется Trusted Publishing.

Настройка один раз:

1. Завести аккаунт на https://pypi.org, включить двухфакторную аутентификацию.
2. https://pypi.org/manage/account/publishing/ → добавить издателя:
   * PyPI Project Name: `indexgap`
   * Owner: `borisowlexa2010-star`
   * Repository name: `indexgap`
   * Workflow name: `publish.yml`
   * Environment name: `pypi`
3. В репозитории: Settings → Environments → New environment → `pypi`.

После этого каждый новый тег вида `v1.1.0` публикует релиз сам.

Если хочется опубликовать вручную прямо сейчас:

```bash
python3 -m pip install --upgrade build twine
python3 -m build
python3 -m twine upload dist/*
```

## Что стоит сделать позже

* Откалибровать профили `events` и `ugc` на живом материале —
  афиши с датами и ленты обсуждений в проверенном портфеле не было,
  и об этом честно написано в шапке `indexgap/profiles.py`.
* Английские сообщения. Сейчас весь вывод и скиллы на русском; для
  англоязычной аудитории GitHub это главный барьер. Интерфейс менять
  не придётся — только вынести строки.
