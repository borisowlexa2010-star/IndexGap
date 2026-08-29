# Как выложить это на GitHub

Репозиторий уже собран: ветка `main`, вся история, теги `v1.0.0` … `v1.4.0`, CI.
Осталось отправить его в пустой репозиторий на GitHub.

Репозиторий создан: <https://github.com/borisowlexa2010-star/Indexgap>
(имя с заглавной `I` — так его создал GitHub, и в командах ниже оно ровно такое).

## Отправить

```bash
cd indexgap
git remote add origin https://github.com/borisowlexa2010-star/Indexgap.git
git push -u origin main
git push origin --tags
```

Если репозиторий создавали с README, лицензией или `.gitignore` — первый push
упрётся в конфликт: всё это уже есть в истории. Тогда либо удалить
и создать пустой, либо один раз `git push --force -u origin main`.

## Сразу после первого push

**Описание** — Settings → About, одной строкой:

> Quality control for programmatic-SEO pipelines: catches invented numbers,
> template-wide breakage, near-duplicates and broken hreflang before you
> publish. Zero dependencies, Python 3.9+, English and Russian output.

**Сайт** — там же: `https://almas.vc/courses/ai-programmatic-seo`

**Темы** — Settings → About → Topics:

```
seo  programmatic-seo  technical-seo  content-quality  hreflang  sitemap
indexnow  search-console  aeo  llm-seo  python  cli  zero-dependencies
static-site-generator  quality-assurance
```

**Проверить, что CI позеленел.** `.github/workflows/tests.yml` гоняет
301 тест на Python 3.9, 3.11 и 3.13 и проверяет, что все девять команд
запускаются. Значок можно вынести в README:

```markdown
![tests](https://github.com/borisowlexa2010-star/Indexgap/actions/workflows/tests.yml/badge.svg)
```

**Создать релиз** из тега `v1.4.0` — Releases → Draft a new release →
выбрать тег → «Generate release notes» или скопировать раздел 1.4.0
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
   * Repository name: `Indexgap`
   * Workflow name: `publish.yml`
   * Environment name: `pypi`
3. В репозитории: Settings → Environments → New environment → `pypi`.

После этого каждый новый тег вида `v1.5.0` публикует релиз сам.

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
* Морфология в сопоставлении `plan` есть только для русского и английского.
  Для сайта на польском или турецком совпадение ключа с заголовком считается
  грубее, чем могло бы.
* `README.ru.md` и русские `SKILL.md` остаются русскими намеренно: это не
  перевод интерфейса, а вторая дверь для русскоязычных студентов курса.
