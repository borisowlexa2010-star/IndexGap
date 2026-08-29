# Как выложить это на GitHub

Репозиторий уже собран: ветка `main`, два коммита, теги `v0.6.0` и `v0.7.0`.
Осталось создать пустой публичный репозиторий и отправить туда историю.

## Вариант 1 — через gh (быстрее всего)

```bash
cd indexgap
gh repo create indexgap --public --source=. --remote=origin --push \
  --description "Lint your programmatic SEO pipeline — from keywords to indexed pages. Pure Python stdlib, no dependencies, no API keys."
git push origin --tags
```

## Вариант 2 — вручную

1. На https://github.com/new создать репозиторий `indexgap`,
   **Public**, без README, без .gitignore, без лицензии
   (всё это уже лежит здесь — иначе будет конфликт).
2. Затем:

```bash
cd indexgap
git remote add origin https://github.com/borisowlexa2010-star/indexgap.git
git push -u origin main
git push origin --tags
```

## После первого пуша

Темы для страницы репозитория (Settings → About → Topics):

```
seo  programmatic-seo  sitemap  indexnow  aeo  geo  python  cli  no-dependencies
```

GitHub Actions заработают сами: `.github/workflows/tests.yml` гоняет
196 тестов на Python 3.9, 3.11 и 3.13 и проверяет, что все восемь команд
запускаются.

## Публикация в PyPI (по желанию)

Имя `indexgap` на PyPI свободно.

```bash
python3 -m pip install --upgrade build twine
python3 -m build
python3 -m twine upload dist/*
```
