#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка единого PDF из всех блоков: текст (A4 портрет) + схемы (A4 альбом)."""
import os, glob
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, PageBreak, NextPageTemplate, Image,
                                Table, TableStyle, KeepTogether)

SRC = "/home/user/ИНСТРУКЦИЯ"
OUT = os.path.join(SRC, "ПОЛНАЯ_ИНСТРУКЦИЯ_Sigur_E510.pdf")

FD = "/usr/share/fonts/truetype/dejavu"
pdfmetrics.registerFont(TTFont("DJ", f"{FD}/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DJ-B", f"{FD}/DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DJM", f"{FD}/DejaVuSansMono.ttf"))
pdfmetrics.registerFont(TTFont("DJM-B", f"{FD}/DejaVuSansMono-Bold.ttf"))

ACC = colors.HexColor("#0b62b8")
INK = colors.HexColor("#1c2430")
MUT = colors.HexColor("#5a6a7e")
LNE = colors.HexColor("#c9d4e0")

PW, PH = A4
LW, LH = landscape(A4)

st_cover_t = ParagraphStyle("ct", fontName="DJ-B", fontSize=26, leading=32,
                            textColor=INK, alignment=TA_CENTER, spaceAfter=6)
st_cover_s = ParagraphStyle("cs", fontName="DJ", fontSize=13, leading=18,
                            textColor=MUT, alignment=TA_CENTER)
st_h1 = ParagraphStyle("h1", fontName="DJ-B", fontSize=19, leading=24,
                       textColor=ACC, spaceBefore=4, spaceAfter=10)
st_h2 = ParagraphStyle("h2", fontName="DJ-B", fontSize=13.5, leading=18,
                       textColor=INK, spaceBefore=10, spaceAfter=5)
st_body = ParagraphStyle("b", fontName="DJ", fontSize=10.5, leading=15,
                         textColor=INK, spaceAfter=5)
st_mono = ParagraphStyle("m", fontName="DJM", fontSize=8.1, leading=9.9,
                         textColor=INK)
st_mono_b = ParagraphStyle("mb", fontName="DJM-B", fontSize=8.1, leading=9.9,
                           textColor=ACC)
st_cap = ParagraphStyle("cap", fontName="DJ", fontSize=10, leading=14,
                        textColor=MUT, alignment=TA_CENTER, spaceBefore=6)
st_img_h = ParagraphStyle("ih", fontName="DJ-B", fontSize=12.5, leading=15,
                          textColor=ACC, spaceAfter=7)
st_toc = ParagraphStyle("toc", fontName="DJ", fontSize=11, leading=22,
                        textColor=INK)


def esc(line):
    line = (line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("☑", "[X]").replace("☐", "[ ]").replace("✓", "+"))
    stripped = line.lstrip(" ")
    n = len(line) - len(stripped)
    return "&nbsp;" * n + stripped


def mono_block(text):
    out = []
    for raw in text.split("\n"):
        if raw.strip() == "":
            out.append(Paragraph("&nbsp;", st_mono))
        elif set(raw.strip()) <= {"="} and len(raw.strip()) > 10:
            out.append(Paragraph(esc(raw), st_mono_b))
        else:
            out.append(Paragraph(esc(raw), st_mono))
    return out


CUR_TITLE = [""]


def on_page(canvas, doc):
    canvas.saveState()
    n = canvas.getPageNumber()
    w = PW if doc.pageTemplate.id == "P" else LW

    canvas.setStrokeColor(LNE)
    canvas.setLineWidth(0.6)
    canvas.line(18 * mm, 14 * mm, w - 18 * mm, 14 * mm)
    canvas.setFont("DJ", 8.5)
    canvas.setFillColor(MUT)
    canvas.drawString(18 * mm, 10 * mm,
                      "СКУД Sigur E510 — дверь + турникет Smartec. Пошаговая инструкция")
    canvas.drawRightString(w - 18 * mm, 10 * mm, f"стр. {n}")
    canvas.restoreState()


doc = BaseDocTemplate(OUT, pagesize=A4, title="СКУД Sigur E510 — полная инструкция",
                      author="Инструкция по монтажу СКУД", subject="Sigur E510, Smartec, РИП-12")
doc.addPageTemplates([
    PageTemplate(id="P", pagesize=A4,
                 frames=[Frame(18 * mm, 18 * mm, PW - 36 * mm, PH - 38 * mm, id="fp")],
                 onPage=on_page),
    PageTemplate(id="L", pagesize=landscape(A4),
                 frames=[Frame(10 * mm, 10 * mm, LW - 20 * mm, LH - 24 * mm, id="fl")],
                 onPage=on_page),
])

S = []
# ---------- обложка ----------
S += [Spacer(1, 42 * mm),
      Paragraph("СКУД на контроллере<br/>Sigur E510", st_cover_t),
      Spacer(1, 6 * mm),
      Paragraph("Дверь с магнитным замком + турникет Smartec", st_cover_s),
      Spacer(1, 3 * mm),
      Paragraph("Пошаговая инструкция для монтажа «с нуля»<br/>"
                "с электрическими схемами на каждый прибор", st_cover_s),
      Spacer(1, 14 * mm)]

cover_img = os.path.join(SRC, "01_Общая_схема_системы.png")
if os.path.exists(cover_img):
    from PIL import Image as PILImage
    iw, ih = PILImage.open(cover_img).size
    w = PW - 40 * mm
    S += [Image(cover_img, width=w, height=w * ih / iw)]
    S += [Paragraph("Общая схема системы", st_cap)]

S += [Spacer(1, 10 * mm)]
info = [["Оборудование", "Sigur E510 ×1, РИП-12 с АКБ, магнитный замок, 4 считывателя Smartec,\n"
                         "зелёная кнопка аварийного открытия + дубль-кнопка, турникет-трипод Smartec"],
        ["Этап 1", "Дверь: магнитный замок, 2 считывателя, кнопка выхода, геркон, аварийное открытие"],
        ["Этап 2", "Турникет: 2 считывателя, кнопка с тремя клавишами"],
        ["Кабель", "Витая пара (LAN) — почти всё; 220 В — только ВВГнг(А)-LS 3×1,5"],
        ["Дата", "26.09.2026"]]
t = Table([[Paragraph(f"<b>{a}</b>", ParagraphStyle("k", fontName="DJ-B", fontSize=9.5,
                                                    leading=13, textColor=ACC)),
            Paragraph(b.replace("\n", "<br/>"), ParagraphStyle("v", fontName="DJ",
                                                               fontSize=9.5, leading=13))]
           for a, b in info], colWidths=[38 * mm, PW - 36 * mm - 38 * mm])
t.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LINEBELOW", (0, 0), (-1, -2), 0.4, LNE),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
]))
S += [t, PageBreak()]

# ---------- содержание ----------
S += [Paragraph("Содержание", st_h1)]
toc = [
    ("01", "Общая схема системы — как всё работает целиком"),
    ("02", "Питание: щиток 220 В → РИП-12 → шина 12 В"),
    ("03", "Контроллер Sigur E510 — назначение клемм"),
    ("04", "Считыватели Wiegand — PORT1…PORT4"),
    ("05", "Магнитный замок через реле K1"),
    ("06", "Геркон двери (D1) и кнопка выхода (D3)"),
    ("07", "Шлейф аварийного открытия (F+ / F−)"),
    ("08", "Турникет Smartec — этап 2"),
    ("09", "Кабельный план: витая пара, раскладка пар, токи"),
    ("10", "Настройка в программе Sigur"),
    ("11", "Проверка и диагностика"),
    ("12", "Что докупить — Ozon.ru"),
]
for num, name in toc:
    S += [Paragraph(f"<b><font color='#0b62b8'>{num}</font></b>&nbsp;&nbsp;{name}", st_toc)]
S += [Spacer(1, 8 * mm),
      Paragraph("Каждый блок = подробная инструкция (текст) + отдельная схема в формате PNG. "
                "Схемы лежат рядом с этим файлом в той же папке, в виде отдельных .png — их удобно "
                "распечатать или держать на экране во время монтажа конкретного узла.", st_body)]
S += [Spacer(1, 6 * mm),
      Paragraph("<b>Правило безопасности:</b> работы с 220 В (клеммы L/N/PE) — только при отключённом "
                "автомате и проверенном отсутствии напряжения. Если опыта в электромонтаже нет — "
                "эти несколько клемм поручите электрику. Всё остальное (12 В) безопасно.", st_body)]
S += [PageBreak()]

# ---------- блоки ----------
blocks = [
    ("01", "Общая схема системы", "01_Общая_схема_системы"),
    ("02", "Питание: РИП-12 и шина 12 В", "02_Питание_РИП-12"),
    ("02b", "Два РИП-12: раздельное питание", "02b_Два_РИП-12_раздельное_питание"),
    ("03", "Контроллер E510 — клеммы", "03_Контроллер_E510_клеммы"),
    ("04", "Считыватели PORT1…PORT4", "04_Считыватели_PORT1-4"),
    ("05", "Магнитный замок — реле K1", "05_Магнитный_замок_K1"),
    ("06", "Геркон и кнопка выхода", "06_Геркон_и_кнопка_выхода"),
    ("07", "Шлейф аварийного открытия", "07_Аварийное_открытие_шлейф"),
    ("08", "Турникет Smartec (этап 2)", "08_Турникет_этап2"),
    ("09", "Кабели — витая пара", "09_Кабели_витая_пара"),
    ("10", "Настройка в программе Sigur", "10_Настройка_Sigur"),
    ("11", "Проверка и диагностика", None),
    ("12", "Что докупить — Ozon.ru", None),
    ("13", "Перенос карточек: Болид → Sigur", "13_Перенос_карточек_Болид_Sigur"),
    ("14", "Настройка Sigur на ПК охраны", "14_Настройка_Sigur_ПК_охраны"),
    ("15", "Программа миграции картотеки", "15_Программа_миграции"),
]

for num, title, stem in blocks:
    # страница-заголовок блока + текст
    S += [Paragraph(f"БЛОК {num}. {title}", st_h1)]
    txt_path = None
    for f in sorted(glob.glob(os.path.join(SRC, f"{num}_*.txt"))):
        txt_path = f
        break
    if txt_path and os.path.exists(txt_path):
        with open(txt_path, encoding="utf-8") as fh:
            S += mono_block(fh.read())
    # схема на альбомной странице
    if stem:
        img = os.path.join(SRC, stem + ".png")
        if os.path.exists(img):
            from PIL import Image as PILImage
            iw, ih = PILImage.open(img).size
            maxw, maxh = LW - 20 * mm - 14, LH - 24 * mm - 52
            sc = min(maxw / iw, maxh / ih)
            S += [NextPageTemplate("L"), PageBreak(),
                  Paragraph(f"БЛОК {num} — СХЕМА: {title}", st_img_h),
                  Image(img, width=iw * sc, height=ih * sc)]
            S += [NextPageTemplate("P"), PageBreak()]
        else:
            S += [PageBreak()]
    else:
        S += [PageBreak()]

doc.build(S)
print("PDF:", OUT, os.path.getsize(OUT), "байт")
