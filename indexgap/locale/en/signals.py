# -*- coding: utf-8 -*-
"""signals — English. Год в заголовке, title и H1, превью, viewport, вес, хабы."""

MESSAGES = {
    "в заголовке {a0} год, а сейчас {a1}: страница обещает свежесть и выглядит заброшенной — шаблон или данные не обновили":
        "the heading says {a0} and it is {a1}: the page promises freshness and looks "
        "abandoned — the template or the data was not updated",
    "title и H1 не делят ни одного слова: «{a0}» и «{a1}» — поисковик может переписать заголовок в выдаче":
        "the title and the H1 share no word: “{a0}” and “{a1}” — the search engine may "
        "rewrite the title in results",
    "нет {a0}: ссылка на страницу в мессенджере или соцсети выйдет без заголовка или картинки":
        "no {a0}: a link to the page in a messenger or a social network shows without a "
        "title or an image",
    "нет <meta name=\"viewport\">: на телефоне страница откроется уменьшенной копией десктопа, а Google индексирует мобильную версию":
        "no <meta name=\"viewport\">: on a phone the page opens as a shrunken desktop "
        "copy, and Google indexes the mobile version",
    "HTML весит {a0:.1f} МБ: Googlebot читает первые 2 МБ файла, остальное в индекс не попадает":
        "the HTML weighs {a0:.1f} MB: Googlebot reads the first 2 MB of a file, the rest "
        "does not reach the index",
    "раздел не ссылается на {a0} из {a1} своих страниц: {a2}{a3} — до них доходят только через sitemap или случайные ссылки":
        "the section does not link to {a0} of its {a1} pages: {a2}{a3} — they are reached "
        "only through the sitemap or stray links",
    " и ещё {a0}": " and {a0} more",
    "картинок тяжелее 1 МБ в сборке: {a0} — {a1}. Они замедляют страницу на телефоне; сожми их или отдай WebP/AVIF":
        "images heavier than 1 MB in the build: {a0} — {a1}. They slow the page down on a "
        "phone; compress them or serve WebP/AVIF",
}
