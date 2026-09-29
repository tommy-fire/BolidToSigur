#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""БЛОК 15 — программа миграции картотеки «загрузил → скачал»."""
import os, cairosvg
from PIL import Image

OUT = "/home/user/ИНСТРУКЦИЯ"
CSS = """
 .bx{fill:#ffffff;stroke:#33475e;stroke-width:2.4}
 .card{fill:#f2f6fb;stroke:#33475e;stroke-width:2.6}
 .hint{fill:#eef2f7;stroke:#9fb2c6;stroke-width:1.6}
 .okbox{fill:#e9f6ec;stroke:#1a7f37;stroke-width:2.2}
 .warnbox{fill:#fdf3e3;stroke:#b45309;stroke-width:2.2}
 .badbox{fill:#fdeaea;stroke:#b91c1c;stroke-width:2.2}
 .t{font-family:"DejaVu Sans";font-weight:bold;font-size:23px;fill:#1c2430}
 .t2{font-family:"DejaVu Sans";font-weight:bold;font-size:19px;fill:#1c2430}
 .l{font-family:"DejaVu Sans";font-size:16px;fill:#2b3a4d}
 .s{font-family:"DejaVu Sans";font-size:14.5px;fill:#5a6a7e}
 .sm{font-family:"DejaVu Sans";font-size:13px;fill:#6a7a8e}
 .tm{fill:#ffffff;stroke:#33475e;stroke-width:1.6}
 .tmg{fill:#eef6ef;stroke:#1a7f37;stroke-width:1.8}
 .tmb{fill:#eef2fb;stroke:#1a5fb4;stroke-width:1.8}
 .tmo{fill:#f4e9d8;stroke:#b45309;stroke-width:1.6}
 .tl{font-family:"DejaVu Sans Mono";font-weight:bold;font-size:15.5px;fill:#1c2430}
 .tl2{font-family:"DejaVu Sans Mono";font-weight:bold;font-size:13px;fill:#1c2430}
 .wr{stroke:#c0392b;stroke-width:3;fill:none}
 .wg{stroke:#2e7d32;stroke-width:2.6;fill:none}
 .wbl{stroke:#1a5fb4;stroke-width:2.6;fill:none}
 .wo{stroke:#e67e22;stroke-width:2.6;fill:none}
 .wd{stroke:#8b95a1;stroke-width:2.4;fill:none;stroke-dasharray:9 6}
"""


def head(w, h, title):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
            f'<style>{CSS}</style>',
            f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
            f'<text class="t" x="34" y="44">{title}</text>',
            f'<line x1="34" y1="58" x2="{w-34}" y2="58" stroke="#0b62b8" stroke-width="3"/>']


def box(x, y, w, h, cls="bx"):
    return f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="7"/>'


def txt(x, y, s, cls="l"):
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<text class="{cls}" x="{x}" y="{y}">{s}</text>'


def term(x, y, w, h, label, cls="tm", tcls="tl2"):
    return (f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="3"/>'
            f'<text class="{tcls}" x="{x+9}" y="{y+h/2+5.5}">{label}</text>')


def pl(pts, cls="wr"):
    return f'<polyline class="{cls}" points="{" ".join(pts)}" fill="none"/>'


def save(name, w, h, body):
    s = "\n".join(head(w, h, name[0]) + body + ['</svg>'])
    p = os.path.join(OUT, "_tmp15.svg")
    open(p, "w", encoding="utf-8").write(s)
    png = os.path.join(OUT, name[1] + ".png")
    cairosvg.svg2png(url=p, write_to=png, scale=2.2)
    os.makedirs("/home/user/_svg", exist_ok=True)
    os.replace(p, "/home/user/_svg/" + name[1] + ".svg")
    print("OK", name[1] + ".png", Image.open(png).size)


# =====================================================================
# 15 — ПРОГРАММА ПЕРЕНОСА КАРТОТЕКИ: «ЗАГРУЗИЛ → СКАЧАЛ»
# =====================================================================
W, H = 1180, 1060
b = []

# --- установка
b += [box(40, 90, 1100, 130, "okbox"),
      txt(56, 118, "УСТАНОВКА (ОДИН РАЗ, минут десять)", "t2"),
      txt(56, 146, "1. Python с сайта www.python.org/downloads — на ПЕРВОМ экране установщика", "l"),
      txt(56, 172, "    поставить галочку «Add Python to PATH», дальше просто Install Now", "l"),
      txt(56, 198, "2. Запустить_миграцию.bat двойным щелчком — сам поставит библиотеки и откроет окно", "l")]

b += [pl(["590,220", "590,258"], "wg")]

# --- что загружаем
b += [box(40, 258, 1100, 150, "card"),
      txt(56, 286, "ЧТО ЗАГРУЖАЕМ — любой файл, выгруженный из «Орион Про»", "t2"),
      term(56, 306, 96, 32, "CSV", "tm", "tl2"),
      term(164, 306, 96, 32, "XML", "tm", "tl2"),
      term(272, 306, 96, 32, "XLS", "tm", "tl2"),
      term(380, 306, 96, 32, "XLSX", "tm", "tl2"),
      txt(500, 328, "— откуда: ImportWizard.exe, «Генератор отчётов», SQL-выгрузка", "l"),
      txt(56, 366, "Кодировки cp1251 / UTF-8 / cp866 и разделители ; , | TAB — определяются сами.", "l"),
      txt(56, 392, "Фотографии могут лежать прямо в выгрузке — программа их найдёт.", "sm")]

b += [pl(["590,408", "590,446"], "wg")]

# --- программа
b += [box(40, 446, 1100, 250),
      txt(56, 474, "ПРОГРАММА — Миграция_Болид_Sigur.pyw (окно с кнопками)", "t2"),
      txt(56, 502, "1. «Обзор…» → выбрали файл → сразу видно, что программа поняла:", "l"),
      txt(56, 528, "     сколько строк, как зовут колонки, сколько кодов карт распознано", "l"),
      txt(56, 554, "2. Сопоставление колонок — программа ставит сама, можно поправить руками", "l"),
      txt(56, 580, "3. Предпросмотр: колонки «Код (как было)» и «В Sigur» — проверить глазами 10–20 строк", "l"),
      term(56, 600, 340, 32, "AE001E006E14F101", "tm", "tl2"),
      txt(404, 622, "→", "t2"),
      term(430, 600, 130, 32, "110,05361", "tmg", "tl2"),
      txt(580, 622, "— если видите такие пары, всё верно", "l"),
      txt(56, 662, "4. Фото: base64 / data-URI / hex распознаются по сигнатуре файла → Фото\\таб№.jpg", "l"),
      txt(56, 688, "Кнопка «СДЕЛАТЬ ФАЙЛ ДЛЯ SIGUR» — и всё.", "l")]

b += [pl(["590,696", "590,734"], "wg")]

# --- результат
b += [box(40, 734, 1100, 160, "okbox"),
      txt(56, 762, "ЧТО СКАЧИВАЕМ (появляется в указанной папке)", "t2"),
      term(56, 782, 260, 32, "Импорт_для_Sigur.xls", "tmg", "tl2"),
      txt(330, 804, "→ Sigur: «Персонал» → «Импорт из таблицы MS Excel»", "l"),
      term(56, 826, 130, 32, "Фото\\", "tmb", "tl2"),
      txt(198, 848, "фотографии сотрудников", "l"),
      term(340, 826, 130, 32, "Отчёт.txt", "tmo", "tl2"),
      txt(482, 848, "читать обязательно", "l"),
      term(700, 826, 240, 32, "Уровни_доступа.csv", "tmb", "tl2"),
      txt(56, 882, "Перед импортом: бэкап базы Sigur («Экспорт базы») → пробные 5 карт → остальные.", "l")]

b += [pl(["590,894", "590,932"], "wo")]

# --- если не поняла
b += [box(40, 932, 1100, 100, "warnbox"),
      txt(56, 960, "ЕСЛИ ПРОГРАММА ЧТО-ТО НЕ ПОНЯЛА", "t2"),
      txt(56, 988, "Кнопка «Диагностика» → появится Диагностика.txt (колонки + первые строки).", "l"),
      txt(56, 1014, "Пришлите этот файл — программа подгоняется под ваш формат за один круг.", "l")]

save(("БЛОК 15 — Программа переноса картотеки: «загрузил → скачал»", "15_Программа_миграции"), W, H, b)
