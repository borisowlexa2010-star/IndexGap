# -*- coding: utf-8 -*-
"""signals — English. Год в заголовке, title и H1, превью, viewport, вес, хабы."""

MESSAGES = {
    "у {a0} из {a1} страниц раздела /{a2} в заголовке {a3} год, а сейчас {a4}: шаблон заголовка не обновили. Например: {a5}":
        "{a0} of {a1} pages of the /{a2} section have {a3} in the heading, and it is {a4}: "
        "the heading template was not updated. For example: {a5}",
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
    "абсолютного адреса в og:image ({a0})": "an absolute address in og:image ({a0})",
    "картинок тяжелее 1 МБ в сборке: {a0} — {a1}. Они замедляют страницу на телефоне; сожми их или отдай WebP/AVIF":
        "images heavier than 1 MB in the build: {a0} — {a1}. They slow the page down on a "
        "phone; compress them or serve WebP/AVIF",
    "страница объявляет lang=«{a0}», а {a1:.0%} букв её текста — {a2}. Поисковик и экранный диктор верят lang и прочтут страницу не на том языке":
        "the page declares lang=“{a0}”, and {a1:.0%} of the letters in its text are {a2}. "
        "Search engines and screen readers trust lang and will read the page as the "
        "wrong language",
    "латиница": "Latin script",
    "кириллица": "Cyrillic script",
    "греческое письмо": "Greek script",
    "армянское письмо": "Armenian script",
    "еврейское письмо": "Hebrew script",
    "арабское письмо": "Arabic script",
    "деванагари": "Devanagari",
    "бенгальское письмо": "Bengali script",
    "гуджаратское письмо": "Gujarati script",
    "тамильское письмо": "Tamil script",
    "телугу": "Telugu script",
    "каннада": "Kannada script",
    "малаялам": "Malayalam script",
    "сингальское письмо": "Sinhala script",
    "тайское письмо": "Thai script",
    "лаосское письмо": "Lao script",
    "бирманское письмо": "Myanmar script",
    "грузинское письмо": "Georgian script",
    "эфиопское письмо": "Ethiopic script",
    "кхмерское письмо": "Khmer script",
    "хангыль": "Hangul",
    "японская кана": "Japanese kana",
    "китайские иероглифы": "Chinese characters",
}
