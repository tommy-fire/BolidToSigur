#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""БЛОК 02b — питание от ДВУХ отдельных РИП-12 (раздельное питание)."""
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
 .wb{stroke:#2b2b2b;stroke-width:3;fill:none}
 .wg{stroke:#2e7d32;stroke-width:2.6;fill:none}
 .wbl{stroke:#1a5fb4;stroke-width:2.6;fill:none}
 .wo{stroke:#e67e22;stroke-width:2.6;fill:none}
 .wf{stroke:#b91c1c;stroke-width:3.4;fill:none}
 .wv{stroke:#b8860b;stroke-width:3;fill:none}
 .wd{stroke:#8b95a1;stroke-width:2.4;fill:none;stroke-dasharray:9 6}
 .bl{font-family:"DejaVu Sans";font-size:13.5px;fill:#0b62b8}
 .rl{font-family:"DejaVu Sans";font-size:13.5px;fill:#a01b1b}
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


def term(x, y, w, h, label, cls="tm", tcls="tl"):
    return (f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="3"/>'
            f'<text class="{tcls}" x="{x+9}" y="{y+h/2+5.5}">{label}</text>')


def pl(pts, cls="wr"):
    return f'<polyline class="{cls}" points="{" ".join(pts)}" fill="none"/>'


def save(name, w, h, body):
    s = "\n".join(head(w, h, name[0]) + body + ['</svg>'])
    p = os.path.join(OUT, "_tmp02b.svg")
    open(p, "w", encoding="utf-8").write(s)
    png = os.path.join(OUT, name[1] + ".png")
    cairosvg.svg2png(url=p, write_to=png, scale=2.2)
    os.makedirs("/home/user/_svg", exist_ok=True)
    os.replace(p, "/home/user/_svg/" + name[1] + ".svg")
    print("OK", name[1] + ".png", Image.open(png).size)


# =====================================================================
W, H = 1180, 940
b = []

# ---------------- 220 В: щиток -> два РИП ----------------
b += [box(40, 84, 210, 110, "card"), txt(56, 112, "ЩИТОК 220 В", "t2"),
      term(56, 130, 84, 28, "B10 №1", "tmb", "tl2"),
      term(150, 130, 84, 28, "B10 №2", "tmb", "tl2")]
b += [pl(["140,141", "290,141", "290,120", "330,120"], "wf"),
      pl(["234,151", "306,151", "306,320", "330,320"], "wf")]
b += [txt(40, 214, "220 В — только ВВГнг(А)-LS 3×1,5; у каждого РИП-12 свой автомат B10", "sm")]

# ---------------- РИП-12 №1 ----------------
b += [box(330, 84, 320, 110), txt(346, 112, "РИП-12 №1 — «МОЗГ»", "t2"),
      txt(346, 134, "E510 + считыватели + кнопки", "sm"),
      term(346, 146, 110, 28, "Авар. сети", "tmo", "tl2"),
      term(470, 140, 78, 30, "+12 В", "tmg", "tl2"),
      term(556, 155, 78, 30, "− GND", "tmb", "tl2")]

# ---------------- РИП-12 №2 ----------------
b += [box(330, 264, 320, 110), txt(346, 292, "РИП-12 №2 — «СИЛА»", "t2"),
      txt(346, 314, "магнитный замок", "sm"),
      term(346, 326, 110, 28, "Авар. сети", "tmo", "tl2"),
      term(470, 320, 78, 30, "+12 В", "tmg", "tl2"),
      term(556, 335, 78, 30, "− GND", "tmb", "tl2")]

# ---------------- потребители ----------------
b += [pl(["548,155", "700,155"], "wr"), pl(["634,170", "700,170"], "wbl"),
      pl(["548,335", "700,335"], "wr"), pl(["634,350", "700,350"], "wbl")]
b += [box(700, 84, 440, 110),
      txt(716, 112, "ПОТРЕБИТЕЛИ №1: ~0,5…0,7 А", "t2"),
      txt(716, 136, "E510 — до 250 мА; 4 считывателя — 150…300 мА", "l"),
      txt(716, 160, "геркон, кнопка выхода, реле, подсветка — ~60 мА", "l"),
      txt(716, 182, "АКБ 17 А·ч → автономность 20 и более часов", "sm")]
b += [box(700, 264, 440, 120),
      txt(716, 292, "ПОТРЕБИТЕЛИ №2: 0,45…1,0 А", "t2"),
      txt(716, 314, "магнитный замок через реле K1 контроллера", "l"),
      term(716, 330, 100, 26, "замок", "tmg", "tl2"),
      term(830, 330, 100, 26, "K1 E510", "tm", "tl2"),
      term(944, 330, 100, 26, "− GND", "tmb", "tl2"),
      pl(["816,343", "830,343"], "wg"), pl(["930,343", "944,343"], "wbl"),
      txt(716, 374, "вся цепь замка — внутри РИП-2, общий «−» с №1 не нужен", "sm")]
b += [txt(700, 214, "красный = +12 В;  синий = «−» GND;  толстая красная = 220 В", "sm")]

# ---------------- три правила ----------------
b += [box(40, 420, 350, 150, "okbox"),
      txt(56, 448, "МОЖНО делить без общей земли", "t2"),
      txt(56, 476, "• Реле K1, K2 — сухой контакт", "l"),
      txt(56, 500, "• Шлейф F+ / F−", "l"),
      txt(56, 524, "• Входы D1…D7, геркон, кнопки", "l"),
      txt(56, 552, "(всё это просто «замыкатели»)", "sm")]
b += [box(410, 420, 350, 150, "warnbox"),
      txt(426, 448, "НУЖНА общая земля (GND)", "t2"),
      txt(426, 476, "• Wiegand D0/D1 считывателя", "l"),
      txt(426, 500, "• любой активный сигнал", "l"),
      txt(426, 524, "если прибор от другого РИП —", "l"),
      txt(426, 552, "минусы РИП соединить перемычкой", "sm")]
b += [box(780, 420, 360, 150, "badbox"),
      txt(796, 448, "НИКОГДА не соединять", "t2"),
      txt(796, 476, "• «+12 В» РИП-1 с «+12 В» РИП-2", "l"),
      txt(796, 500, "• 220 В и 12 В в одном кабеле", "l"),
      txt(796, 524, "• GND турникета с 12 В без нужды", "l")]

# ---------------- перемычка GND + проверка ----------------
b += [box(40, 600, 520, 150, "warnbox"),
      txt(56, 628, "ПЕРЕМЫЧКА GND (только если надо)", "t2"),
      txt(56, 656, "«−» РИП-1  ────────  «−» РИП-2", "l"),
      txt(56, 684, "отдельная жила, 2+2 витой пары, как можно короче", "sm"),
      txt(56, 712, "«+» НЕ соединять никогда — это уже короткое замыкание", "rl")]
b += [box(600, 600, 540, 150, "card"),
      txt(616, 628, "ПРОВЕРКА мультиметром (РИП без 220 В)", "t2"),
      txt(616, 656, "«−» РИП-1 ↔ «−» РИП-2 ..... ~0 Ом (перемычка есть)", "l"),
      txt(616, 684, "«+» РИП-1 ↔ «+» РИП-2 ..... бесконечность (не соединены)", "l"),
      txt(616, 712, "«+» ↔ «−» любого РИП ...... не КЗ (десятки Ом = катушка)", "sm")]

# ---------------- DCD ----------------
b += [box(40, 790, 1100, 110, "card"),
      txt(56, 818, "DCD: авария любого из двух РИП-12", "t2"),
      txt(56, 844, "«Авария сети» №1 и №2 объединить по логике ИЛИ: НО-контакты — параллельно, НЗ — последовательно.", "l"),
      txt(56, 870, "Тип контакта — по наклейке РИП, либо прозвоните мультиметром при включённом и выключенном 220 В.", "l")]

save(("БЛОК 02b — Два РИП-12: раздельное питание", "02b_Два_РИП-12_раздельное_питание"), W, H, b)
