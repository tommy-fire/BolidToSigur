#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
КОНВЕРТЕР: экспорт «Орион Про» (Болид)  ->  таблица импорта Sigur (.xls)

Что делает:
  1. Читает CSV/Excel-выгрузку из АРМ «Орион Про» (автоопределение кодировки
     и разделителя, автоопределение колонок по названиям).
  2. Преобразует коды карт в формат, который понимает Sigur:
       8 байт hex  ->  XXX,XXXXX  (фасилити-код, номер)   [правило из документации Sigur]
  3. Собирает иерархию отделов, склеивает ФИО, группирует несколько карт
     одного сотрудника (до 5 — как требует Sigur).
  4. Пишет готовый .xls для кнопки «Импорт из таблицы MS Excel».
  5. Пишет отчёт: сколько разобрано, сколько не получилось и почему.

Запуск:
    python3 Конвертер_Орион_в_Sigur.py выгрузка.csv
    python3 Конвертер_Орион_в_Sigur.py выгрузка.csv -o готовый.xls

Файлы на выходе (рядом с исходным):
    <имя>_для_Sigur.xls      — импортировать в Sigur
    <имя>_отчёт.txt          — разбор полёта, читать обязательно
    <имя>_уровни_доступа.csv — кто каким уровнем доступа пользовался
"""
import sys, os, csv, re, argparse

# ----------------------------------------------------------------- чтение
ENCODINGS = ("utf-8-sig", "cp1251", "utf-8", "cp866", "latin-1")
DELIMS = (";", "\t", ",", "|")


def sniff(path):
    """Возвращает (заголовки, строки) — пробует кодировки и разделители."""
    raw = open(path, "rb").read()
    best = None
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        for d in DELIMS:
            first = text.split("\n")[0]
            ncols = len(next(csv.reader([first], delimiter=d)))
            if best is None or ncols > best[0]:
                best = (ncols, text, d, enc)
        if best and best[0] > 1:
            break
    if not best:
        raise SystemExit("Не удалось прочитать файл ни в одной кодировке.")
    _, text, delim, enc = best
    rows = list(csv.reader(text.splitlines(), delimiter=delim))
    rows = [r for r in rows if any(c.strip() for c in r)]
    return rows[0], rows[1:], enc, delim


def norm(s):
    return re.sub(r"[^a-zа-яё0-9]", "", (s or "").strip().lower())


ALIASES = {
    "fio":      ("фио", "фio", "fio", "сотрудник", "fullname", "name", "фиофио"),
    "surname":  ("фамилия", "surname", "lastname", "name"),
    "first":    ("имя", "firstname", "first", "name1"),
    "middle":   ("отчество", "middlename", "midname", "patronymic"),
    "tab":      ("табельныйномер", "табномер", "табельный", "tabnumber", "tabno", "tabnomer", "personnelnumber"),
    "dept":     ("отдел", "подразделение", "department", "dept", "структура", "company", "организация", "фирма"),
    "post":     ("должность", "position", "post", "appointment", "profession"),
    "code":     ("код", "кодключа", "code", "codep", "ключ", "идентификатор", "card", "cardcode",
                 "wiegand", "wiegand26", "пропуск", "идентификатордоступа", "кодкарты"),
    "level":    ("уровеньдоступа", "уровень", "accesslevel", "access", "доступ", "полномочия"),
    "finish":   ("срокдействия", "срок", "finish", "действуетдо", "датаокончания", "окончание", "validuntil"),
    "phone":    ("телефон", "phone", "тел"),
    "note":     ("примечание", "комментарий", "note", "comment", "описание"),
}


def find_col(headers, key):
    """Ищет колонку по списку возможных названий."""
    hs = [(i, norm(h)) for i, h in enumerate(headers)]
    for alias in ALIASES[key]:
        for i, h in hs:
            if h == alias:
                return i
    for alias in ALIASES[key]:
        for i, h in hs:
            if h.startswith(alias) or alias in h:
                return i
    return None


# ------------------------------------------------------------ коды карт
HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


def extract_w26(h8):
    """
    8 байт hex -> (фасилити, номер).
    Правило из официальной статьи Sigur:
      взять 4 правых байта, отбросить последний,
      левый из оставшихся трёх — фасилити-код,
      два остальных — номер карты.
    """
    b = bytes.fromhex(h8)
    if len(b) < 7:
        return None
    fac, num = b[-4], (b[-3] << 8) | b[-2]
    return fac, num


def decode_raw_codep(s):
    """
    Сырое значение поля CodeP из БД (двоичные данные).
    Алгоритм: перевернуть байты -> hex -> заменить 01fe на 00 ->
              отбросить хвостовое 08 -> взять первые 16 hex-знаков.
    """
    try:
        b = s.encode("cp1251", errors="ignore")
    except Exception:
        return None
    h = b[::-1].hex()
    h = h.replace("01fe", "00").replace("fe01", "00")
    if h.endswith("08"):
        h = h[:-2]
    return h[:16] or None


def parse_code(raw):
    """
    -> (код_для_Sigur, как_поняли, уверенность)
    """
    if raw is None:
        return None, "пусто", False
    s = str(raw).strip().strip('"').strip("'")
    if not s or s.lower() in ("none", "null", "-", "—"):
        return None, "пусто", False

    # 1) уже готовый формат Sigur: 110,05361
    if re.fullmatch(r"\d{1,3}\s*,\s*\d{1,5}", s):
        a, b = s.split(",")
        return f"{int(a)},{int(b):05d}", "уже W26", True

    s2 = s.replace(" ", "").replace("-", "").replace("0x", "").replace("0X", "")

    # 2) шестнадцатеричный код
    if HEX_RE.fullmatch(s2):
        n = len(s2)
        if n == 16:                      # 8 байт — основной случай Болид
            r = extract_w26(s2)
            if r:
                return f"{r[0]},{r[1]:05d}", "8 байт hex → W26", True
        if n == 6:                       # 3 байта: фасилити + номер
            r = extract_w26("00" * 4 + s2 + "00")
            if r:
                return f"{r[0]},{r[1]:05d}", "3 байта hex → W26", True
        if n in (8, 10, 14):             # W34 / W42 / W58 — Sigur принимает как есть
            return s2.lower(), f"{n} hex (W{ {8:34, 10:42, 14:58}[n] })", True
        if n >= 16:                      # обрезаем до 8 байт и пробуем снова
            r = extract_w26(s2[-16:])
            if r:
                return f"{r[0]},{r[1]:05d}", "обрезано до 8 байт", False
        return s2, f"непонятная длина hex ({n})", False

    # 3) сырое двоичное поле CodeP
    dec = decode_raw_codep(s)
    if dec and len(dec) == 16 and HEX_RE.fullmatch(dec):
        r = extract_w26(dec)
        if r:
            return f"{r[0]},{r[1]:05d}", "CodeP (бинарный) → W26", False

    # 4)十进制 — оставляем как есть, но без уверенности
    if s2.isdigit():
        return s2, "только цифры — проверить вручную", False

    return None, f"не разобрано: {s[:40]}", False


# ------------------------------------------------------------------- сбор
def build(headers, rows):
    c = {k: find_col(headers, k) for k in ALIASES}
    if c["code"] is None:
        raise SystemExit("Не нашёл колонку с кодом карты. Заголовки файла:\n  "
                         + "\n  ".join(headers))

    def g(row, key):
        i = c[key]
        return row[i].strip() if i is not None and i < len(row) else ""

    people, problems, levels = {}, [], []
    for n, row in enumerate(rows, start=2):
        raw_code = g(row, "code")
        code, how, ok = parse_code(raw_code)
        tab = g(row, "tab")

        if c["fio"] is not None:
            fio = g(row, "fio")
        else:
            fio = " ".join(x for x in (g(row, "surname"), g(row, "first"), g(row, "middle")) if x)
        fio = re.sub(r"\s+", " ", fio).strip()
        if not fio:
            fio = g(row, "surname") or f"Строка {n}"

        dept = re.sub(r"\s+", " ", g(row, "dept")).strip()
        key = (tab, fio, dept) if tab else (fio, dept)

        p = people.setdefault(key, {
            "fio": fio, "dept": dept, "post": g(row, "post"), "tab": tab,
            "phone": g(row, "phone"), "note": g(row, "note"), "codes": [],
        })
        if code:
            p["codes"].append((code, g(row, "finish")))
        else:
            problems.append((n, fio, raw_code, how))
        if c["level"] is not None and g(row, "level"):
            levels.append((fio, dept, g(row, "level"), code or ""))

    return people, problems, levels, c


def write_xls(people, out):
    """Пишет .xls для импорта в Sigur. Все ячейки — текстовый формат."""
    import xlwt
    TXT = xlwt.easyxf(num_format_str="@")
    HDR = xlwt.easyxf("font: bold on; pattern: pattern solid, fore_colour 0x16", num_format_str="@")
    cols = ["ФИО", "Отдел", "Должность", "Номер пропуска", "Срок действия",
            "Табельный номер", "Номер телефона", "Тип записи", "Примечание"]
    widths = (9000, 8000, 8000, 6000, 5500, 6000, 6000, 5500, 9000)

    wb = xlwt.Workbook(encoding="utf-8")
    ws = wb.add_sheet("Импорт", cell_overwrite_ok=True)
    for i, h in enumerate(cols):
        ws.write(0, i, h, HDR)
        ws.col(i).width = widths[i]

    r = 1
    for p in people.values():
        codes = p["codes"] or [("", "")]          # сотрудник без кода попадёт пустой строкой
        for j, (code, fin) in enumerate(codes[:5]):   # Sigur принимает максимум 5 пропусков
            vals = [p["fio"], p["dept"], p["post"], code, fin,
                    p["tab"], p["phone"], "Сотрудник", p["note"]] if j == 0 \
                   else ["", "", "", code, fin, "", "", "", ""]
            for i, v in enumerate(vals):
                ws.write(r, i, v, TXT)
            r += 1
    wb.save(out)
    return r - 1


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("src")
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()

    src = a.src
    headers, rows, enc, delim = sniff(src)
    people, problems, levels, cols = build(headers, rows)

    base = os.path.splitext(src)[0]
    out_xls = a.out or base + "_для_Sigur.xls"

    nrows = write_xls(people, out_xls)

    rep = base + "_отчёт.txt"
    total_codes = sum(len(p["codes"]) for p in people.values())
    with open(rep, "w", encoding="utf-8") as f:
        f.write("ОТЧЁТ КОНВЕРТАЦИИ «Орион Про» -> Sigur\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"Файл .................... {os.path.basename(src)}\n")
        f.write(f"Кодировка / разделитель . {enc} / {delim!r}\n")
        f.write(f"Строк в выгрузке ........ {len(rows)}\n")
        f.write(f"Сотрудников ............. {len(people)}\n")
        f.write(f"Кодов карт распознано ... {total_codes}\n")
        f.write(f"Не распознано ........... {len(problems)}\n\n")
        f.write("НАЙДЕННЫЕ КОЛОНКИ:\n")
        for k, i in cols.items():
            f.write(f"  {k:9s} -> {headers[i] if i is not None else '— НЕ НАЙДЕНА —'}\n")
        if problems:
            f.write("\nСТРОКИ, КОТОРЫЕ НЕ УДАЛОСЬ РАЗОБРАТЬ:\n")
            for n, fio, raw, how in problems[:50]:
                f.write(f"  строка {n}: {fio} | «{raw}» | {how}\n")
            if len(problems) > 50:
                f.write(f"  ...и ещё {len(problems)-50}\n")
        if total_codes:
            f.write("\nПРИМЕРЫ ПРЕОБРАЗОВАНИЯ (первые 10):\n")
            shown = 0
            for p in people.values():
                for code, _ in p["codes"]:
                    f.write(f"  {p['fio'][:35]:37s} -> {code}\n")
                    shown += 1
                    if shown >= 10:
                        break
                if shown >= 10:
                    break

    if levels:
        lv = base + "_уровни_доступа.csv"
        with open(lv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["ФИО", "Отдел", "Уровень доступа (Орион)", "Код карты"])
            w.writerows(levels)
        print("OK", lv)

    print("OK", out_xls, f"— сотрудников: {len(people)}, кодов: {total_codes}, проблем: {len(problems)}")
    print("OK", rep)


if __name__ == "__main__":
    main()
