#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
МИГРАЦИЯ КАРТОТЕКИ: «Орион Про» (Болид)  ->  Sigur

Работает по принципу «загрузил — скачал»:
  1. Указываете файл, выгруженный из «Орион Про» (csv, xml, xls, xlsx — любой).
  2. Программа сама разбирает его и ПОКАЗЫВАЕТ, что поняла.
  3. Нажимаете «Сделать файл для Sigur» — получаете готовый .xls
     (+ папку с фотографиями, если они были в выгрузке).

Никакого подключения к живой базе: всё читается из файла.
"""
import os, re, sys, csv, base64, shutil, traceback

APP = "Миграция «Орион Про» → Sigur"
VER = "v.01"

# ============================================================ чтение файла
def read_any(path):
    """-> (заголовки, строки). Поддержка csv/txt/xml/xls/xlsx."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xls", ".xlsx"):
        return read_excel(path)
    if ext == ".xml":
        return read_xml(path)
    return read_delimited(path)


def read_delimited(path):
    raw = open(path, "rb").read()
    best = None
    for enc in ("utf-8-sig", "cp1251", "utf-8", "cp866", "latin-1"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        for d in (";", "\t", ",", "|"):
            n = len(next(csv.reader([text.split("\n")[0]], delimiter=d)))
            if best is None or n > best[0]:
                best = (n, text, d, enc)
        if best and best[0] > 1:
            break
    if not best:
        raise ValueError("Не удалось прочитать файл ни в одной кодировке")
    _, text, delim, enc = best
    rows = [r for r in csv.reader(text.splitlines(), delimiter=delim) if any(c.strip() for c in r)]
    return rows[0], rows[1:], f"{enc}, разделитель {delim!r}"


def read_excel(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active
        rows = [[("" if c is None else str(c)) for c in r] for r in ws.values]
    else:
        import xlrd
        wb = xlrd.open_workbook(path)
        ws = wb.sheet_by_index(0)
        rows = [[str(ws.cell_value(r, c)) for c in range(ws.ncols)] for r in range(ws.nrows)]
    rows = [r for r in rows if any(c.strip() for c in r)]
    return rows[0], rows[1:], "Excel"


def read_xml(path):
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    recs = []
    for el in root.iter():
        if len(el) and all(len(list(c)) == 0 for c in el):
            recs.append(el)
    if not recs:
        recs = list(root)
    out, headers = [], []
    for el in recs:
        d = dict(el.attrib)
        for c in el:
            d[c.tag] = (c.text or "").strip()
        for k in d:
            if k not in headers:
                headers.append(k)
        out.append(d)
    rows = [[r.get(h, "") for h in headers] for r in out]
    return headers, rows, "XML"


# ============================================================ разбор кодов
HEX_RE = re.compile(r"^[0-9a-fA-F]+$")

# Формат карт на считывателях: "W26" или "W34".
# Ставится из окна программы. От него зависит, как 8-байтный код из базы
# «Ориона» превращается в номер пропуска Sigur.
CARD_FORMAT = "W26"

# Правило вырезания номера карты из кода «Ориона», подобранное сверкой
# по карте с известным номером: (база, отступ, переворот, длина_окна).
# None — простые правила (правые 8 hex для W34, байты 5–7 для W26).
FITTED_RULE = None
FIT_INFO = ""      # описание подобранного правила — в журнал и отчёт


def extract_w26(h8):
    b = bytes.fromhex(h8)
    if len(b) < 7:
        return None
    return b[-4], (b[-3] << 8) | b[-2]


def decode_raw_codep(s):
    """Сырое двоичное поле CodeP из БД «Орион Про»."""
    try:
        b = s.encode("cp1251", errors="ignore")
    except Exception:
        return None
    h = b[::-1].hex()
    h = h.replace("01fe", "00").replace("fe01", "00")
    if h.endswith("08"):
        h = h[:-2]
    return h[:16] or None


def _display_candidates(s):
    """Все прочтения кода «как в АБД „Ориона“».

    В базе код лежит ПЕРЕВЁРНУТЫМ по байтам, а вместо байта 00 — вставки-
    экраны (FE 01 или 01 FE 01). Разворачиваем и убираем экраны; где
    разбор неоднозначен — перебираем все варианты (их немного).
    Если на входе уже обычный код (заканчивается на 01) — он тоже вариант."""
    outs = set()
    sl = s.lower()
    if sl.endswith("01"):
        outs.add(sl)                       # вход уже похож на код из АБД
    try:
        r = bytes.fromhex(sl)[::-1]
    except ValueError:
        return sorted(outs)

    def rec(i, acc):
        if len(outs) > 16:                 # защита от разрастания перебора
            return
        if i == len(r):
            outs.add(bytes(acc).hex())
            return
        x = r[i]
        if x == 0xFE and i + 1 < len(r) and r[i + 1] == 0x01:
            rec(i + 2, acc + [0])                       # FE 01 -> 00
        elif x == 0x01 and i + 1 < len(r) and r[i + 1] == 0xFE:
            if i + 2 < len(r) and r[i + 2] == 0x01:
                rec(i + 3, acc + [0])                   # 01 FE 01 -> 00
            rec(i + 2, acc + [0])                       # 01 FE -> 00
            rec(i + 1, acc + [x])                       # 01 — настоящий байт
        else:
            rec(i + 1, acc + [x])
    rec(0, [])
    return sorted(outs)


def w34_theory(s):
    """Номер W34 по правилу «8 знаков до 01 в конце кода».

    Код карты в АБД «Ориона» заканчивается служебным хвостом «01», а
    перед хвостом стоит 8-значный HEX-номер — тот самый, который ждёт
    Sigur. Берём 8 знаков, отсчитав 3 от конца.
    -> (номер или None, причина). Причина «неоднозначно» — код допускает
    несколько прочтений (например, два нулевых байта подряд у старых
    карт); номер такой карты лучше завести вручную захватом."""
    by_len = {}
    for d in _display_candidates(s):
        if d.endswith("01") and len(d) >= 14:
            by_len.setdefault(len(d), set()).add(d[-11:-3])
    if not by_len:
        return None, "не похоже на код Болид"
    # каноническая длина кода карты — 16 знаков; её и берём
    L = sorted(by_len, key=lambda z: (z != 16, z))[0]
    vals = by_len[L]
    if len(vals) == 1:
        return vals.pop().upper(), ""
    return None, "неоднозначно"


def w34_by_theory(s):
    """Только номер (для сверки) или None."""
    return w34_theory(s)[0]


def _code_bases(s):
    """Варианты прочтения hex-кода: как есть / байты наоборот / расшифровка
    Болида (в базе код лежит перевёрнутым, а вместо нулей — вставки 01FE)."""
    res = [("код", s)]
    if len(s) >= 2 and len(s) % 2 == 0:
        try:
            r = bytes.fromhex(s)[::-1].hex()
        except ValueError:
            return res
        res.append(("код наоборот", r))
        d = r.replace("01fe", "00").replace("fe01", "00")
        if d.endswith("08"):
            d = d[:-2]
        if d:
            res.append(("расшифровка Болида", d))
    return res


def _rule_name(rule):
    bname, off, rev, wl = rule
    if bname == "код АБД":
        return "код АБД: 8 знаков до 01 в конце"
    return f"{bname}: знаки {off + 1}–{off + wl}" + (", оттуда наоборот" if rev else "")


def _rule_value(s, rule, fmt):
    """Номер пропуска по правилу для одного кода (или None)."""
    bname, off, rev, wl = rule
    if bname == "код АБД":
        v = w34_by_theory(s)
        return v if fmt == "W34" else None
    base = dict(_code_bases(s)).get(bname)
    if base is None or off + wl > len(base):
        return None
    w = base[off:off + wl]
    if not HEX_RE.fullmatch(w):
        return None
    if rev:
        try:
            w = bytes.fromhex(w)[::-1].hex()
        except ValueError:
            return None
    if fmt == "W34":
        return w.upper()
    if len(w) == 16:
        r = extract_w26(w)
        if r:
            return f"{r[0]},{r[1]:05d}"
    elif len(w) == 6:
        return f"{int(w[:2], 16)},{int(w[2:], 16):05d}"
    return None


def _norm_hex(raw):
    s = str(raw).strip().strip('"').strip("'").replace(" ", "").replace("-", "")
    if s[:2].lower() == "0x":
        s = s[2:]
    return s if HEX_RE.fullmatch(s) else None


def fit_card_rule(known, codes, fmt):
    """Подбор правила вырезания номера по карте с ИЗВЕСТНЫМ номером.

    В базе «Ориона» код карты лежит перевёрнутым и со служебными вставками,
    и место номера в нём зависит от версии базы. Вместо того чтобы угадывать,
    перебираем варианты и находим тот, который даёт номер известной карты.
    -> (правило, имя, нормализованный номер) или (None, None, номер).
    """
    kn = str(known).strip().upper().replace(" ", "")
    if kn[:2] == "0X":
        kn = kn[2:]
    if fmt == "W34":
        if not re.fullmatch(r"[0-9A-F]{8}", kn):
            return None, None, kn
    else:
        m = re.fullmatch(r"(\d{1,3}),(\d{1,5})", kn)
        if not m:
            return None, None, kn
        kn = f"{int(m.group(1))},{int(m.group(2)):05d}"

    hexes = []
    for c in codes:
        h = _norm_hex(c)
        if h and len(h) >= 8:
            hexes.append(h)
    if not hexes:
        return None, None, kn

    # 1) ГЛАВНОЕ ПРАВИЛО: 8 знаков до 01 в конце кода АБД — сверяем
    #    по известной карте; если совпало, применяем ко всему файлу
    if fmt == "W34":
        for h in hexes:
            if w34_by_theory(h) == kn:
                rule = ("код АБД", -11, False, 8)
                return rule, _rule_name(rule), kn

    matches = []
    for h in hexes:
        for bname, base in _code_bases(h):
            n = len(base)
            for wl in ((8,) if fmt == "W34" else (16, 6)):
                # шаг 1 hex-знак: номер в коде «Ориона» может быть смещён
                # на полбайта (внутри кода лежит Wiegand-поток с чётностью)
                for off in range(0, n - wl + 1):
                    for rev in (False, True):
                        w = base[off:off + wl]
                        if rev:
                            try:
                                w = bytes.fromhex(w)[::-1].hex()
                            except ValueError:
                                continue
                        if fmt == "W34":
                            val = w.upper()
                        elif len(w) == 16:
                            r = extract_w26(w)
                            val = f"{r[0]},{r[1]:05d}" if r else None
                        else:
                            val = f"{int(w[:2], 16)},{int(w[2:], 16):05d}"
                        if val == kn:
                            rule = (bname, off, rev, wl)
                            if rule not in matches:
                                matches.append(rule)
    if not matches:
        return None, None, kn

    # из совпавших берём правило, применимое к наибольшему числу кодов
    def score(rule):
        return sum(1 for h in hexes if _rule_value(h, rule, fmt))

    best = matches[0]
    for r in matches[1:]:
        if score(r) > score(best):
            best = r
    return best, _rule_name(best), kn


def parse_code(raw):
    """-> (код для Sigur, как поняли)"""
    if raw is None:
        return None, "пусто"
    s = str(raw).strip().strip('"').strip("'")
    if not s or s.lower() in ("none", "null", "-", "—"):
        return None, "пусто"

    if re.fullmatch(r"\d{1,3}\s*,\s*\d{1,5}", s):
        a, b = s.split(",")
        return f"{int(a)},{int(b):05d}", "уже W26"

    s2 = s.replace(" ", "").replace("-", "").replace("0x", "").replace("0X", "")
    if HEX_RE.fullmatch(s2):
        n = len(s2)
        if CARD_FORMAT == "W34":
            if FITTED_RULE:
                v = _rule_value(s2, FITTED_RULE, "W34")
                if v and len(v) == 8:
                    return v, "по сверке: " + _rule_name(FITTED_RULE)
                if FITTED_RULE[0] == "код АБД" and w34_theory(s2)[1] == "неоднозначно":
                    return None, "код читается неоднозначно — завести карту захватом"
                return None, "код не подходит под правило сверки — прислать образец"
            v, why = w34_theory(s2)
            if v:
                return v, "W34: 8 знаков до 01 в конце кода (правило Болид)"
            if why == "неоднозначно":
                return None, "код читается неоднозначно — завести карту захватом"
            if n >= 16:
                return s2[-8:].upper(), "W34: правые 8 hex — СВЕРИТЬ с Sigur"
            if n == 8:
                return s2.upper(), "W34 (как есть)"
            if n in (10, 14):
                return s2.upper(), f"W{ {10: 42, 14: 58}[n] } (как есть)"
            if n == 6:
                return None, "6 hex при формате W34 — прислать образец"
            return s2, f"непонятная длина ({n})"
        if FITTED_RULE:
            v = _rule_value(s2, FITTED_RULE, "W26")
            if v:
                return v, "по сверке: " + _rule_name(FITTED_RULE)
        if n == 16:
            r = extract_w26(s2)
            if r:
                return f"{r[0]},{r[1]:05d}", "8 байт → W26"
        if n == 6:
            r = extract_w26("00000000" + s2 + "00")
            if r:
                return f"{r[0]},{r[1]:05d}", "3 байта → W26"
        if n in (8, 10, 14):
            return s2.lower(), f"{n} hex (W{ {8: 34, 10: 42, 14: 58}[n] })"
        if n > 16:
            r = extract_w26(s2[-16:])
            if r:
                return f"{r[0]},{r[1]:05d}", "обрезано до 8 байт"
        return s2, f"непонятная длина ({n})"

    dec = decode_raw_codep(s)
    if dec and len(dec) == 16 and HEX_RE.fullmatch(dec):
        if CARD_FORMAT == "W34":
            v, why = w34_theory(dec)
            if v:
                return v, "W34: 8 знаков до 01 в конце кода (правило Болид)"
            if why == "неоднозначно":
                return None, "код читается неоднозначно — завести карту захватом"
            return dec[-8:].upper(), "W34: правые 8 hex — СВЕРИТЬ с Sigur"
        r = extract_w26(dec)
        if r:
            return f"{r[0]},{r[1]:05d}", "CodeP (бинарный) → W26"

    if s2.isdigit():
        return s2, "только цифры — проверить"

    return None, "не разобрано"


# ============================================================ даты
DATE_RE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}([ T]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?)?$"
                     r"|^\d{1,2}[./]\d{1,2}[./]\d{4}([ T]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?)?$")


def norm_date(s):
    """Приводим дату к виду ДД.ММ.ГГГГ — так просит Sigur при импорте."""
    if s is None:
        return ""
    s = str(s).strip()
    if not s:
        return ""
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T]|$)", s)
    if m:
        return f"{int(m.group(3)):02d}.{int(m.group(2)):02d}.{m.group(1)}"
    m = re.match(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
    if m:
        return f"{int(m.group(1)):02d}.{int(m.group(2)):02d}.{m.group(3)}"
    return s


def detect_date_col(headers, rows, mapping):
    """Если «Срок действия» не назначена — ищем колонку, похожую на даты.

    В выгрузке из «Болида» эта колонка часто называется внутренним именем
    базы, поэтому угадываем по содержимому (значения похожи на даты)
    и по названию (срок/действует/до/end...). Возвращает (mapping, имя)."""
    if mapping.get("finish") is not None:
        return mapping, ""
    hints = ("срок", "действ", "окончан", "до", "end", "valid", "until",
             "expire", "дата", "finish")
    best, best_score, best_name = None, 0.0, ""
    busy = {i for i in mapping.values() if i is not None}
    for i, h in enumerate(headers):
        if i in busy:
            continue
        hn = norm(h)
        if ("рожден" in hn or "birth" in hn or "выдач" in hn or "issue" in hn
                or "pasport" in hn or "passport" in hn or "start" in hn
                or "создан" in hn or "creation" in hn or "document" in hn
                or "документ" in hn or "kodpodr" in hn or "kem" in hn):
            continue                                  # это точно не срок
        vals = [r[i].strip() for r in rows if i < len(r) and r[i].strip()]
        if not vals:
            continue
        frac = sum(1 for v in vals if DATE_RE.match(v)) / len(vals)
        if frac < 0.3:
            continue
        score = frac + (0.5 if any(k in hn for k in hints) else 0.0)
        if score > best_score:
            best, best_score, best_name = i, score, h
    if best is not None:
        mapping["finish"] = best
        return mapping, best_name
    return mapping, ""


# ============================================================ фотографии
MAGIC = [(b"\xff\xd8\xff", ".jpg"), (b"\x89PNG", ".png"),
         (b"GIF8", ".gif"), (b"BM", ".bmp")]


def sniff_ext(data):
    for m, e in MAGIC:
        if data[:len(m)] == m:
            return e
    return None


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|]', "_", str(s)).strip().strip(".")
    return (s or "фото")[:80]


def same_file(a, b):
    """Это один и тот же файл? (на Windows регистр букв не важен)"""
    try:
        return os.path.samefile(a, b)
    except Exception:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def copy_photo(src, dst):
    """Копируем фото, не падая.

    Если источник и получатель — один и тот же файл (папка результата
    совпала с папкой выгрузки), ничего копировать не нужно: фото уже на месте.
    Если файл чем-то занят — пробуем прочитать и записать сами."""
    if same_file(src, dst):
        return True
    try:
        shutil.copy2(src, dst)
        return True
    except PermissionError:
        try:
            data = open(src, "rb").read()
            open(dst, "wb").write(data)
            return True
        except Exception:
            return False
    except Exception:
        return False


def extract_photo(value, outdir, base, src_dir=""):
    """Пытается достать фото из значения ячейки -> имя файла или ''.

    Понимает: путь к файлу (абсолютный или относительно папки с исходным
    файлом), base64 (в т.ч. с префиксом data:image/...) и шестнадцатеричный
    поток. Главная проверка — по сигнатуре файла, а не по размеру.
    """
    if not value:
        return ""
    s = str(value).strip()
    if len(s) < 4:
        return ""

    def save(data, ext):
        if len(data) < 60:
            return ""
        e = sniff_ext(data) or ext
        if not sniff_ext(data) and ext is None:
            return ""
        fn = safe_name(base) + e
        open(os.path.join(outdir, fn), "wb").write(data)
        return fn

    # 1) путь к файлу на диске — абсолютный или относительно исходного файла
    if len(s) < 400:
        real = None
        for cand in (s, s.replace("\\", "/")):
            if os.path.isfile(cand):
                real = cand
                break
            if src_dir:
                j = os.path.join(src_dir, cand)
                if os.path.isfile(j):
                    real = j
                    break
        if real is None and src_dir and "/" not in s and "\\" not in s:
            # короткое имя («7.jpg») — могла иметься в виду папка с фотографиями
            for sub in ("Фотографии", "Фото"):
                j = os.path.join(src_dir, sub, s)
                if os.path.isfile(j):
                    real = j
                    break
        if real:
            ext = os.path.splitext(real)[1] or ".jpg"
            fn = safe_name(base) + ext
            if copy_photo(real, os.path.join(outdir, fn)):
                return fn
            return ""

    # 2) base64, в том числе с префиксом data:image/jpeg;base64,...
    s64 = re.sub(r"^data:image/[a-zA-Z0-9.+-]*;base64,", "", s)
    if len(s64) > 40 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", s64):
        try:
            data = base64.b64decode(re.sub(r"\s", "", s64))
        except Exception:
            data = b""
        if sniff_ext(data):
            return save(data, ".jpg")

    # 3) шестнадцатеричный поток
    s16 = re.sub(r"[\s\-]", "", s)
    if len(s16) > 80 and len(s16) % 2 == 0 and HEX_RE.fullmatch(s16):
        try:
            data = bytes.fromhex(s16)
        except Exception:
            data = b""
        if sniff_ext(data):
            return save(data, ".jpg")
    return ""


# ============================================================ колонки
ALIASES = {
    "fio":     ("фио", "fio", "сотрудник", "fullname", "имяполностью"),
    "surname": ("фамилия", "surname", "lastname", "name", "last"),
    "first":   ("имя", "firstname", "first"),
    "middle":  ("отчество", "middlename", "midname", "patronymic"),
    "tab":     ("табельныйномер", "табномер", "табельный", "tabnumber",
                "tabno", "personnelnumber", "таб№"),
    "dept":    ("отдел", "подразделение", "department", "dept", "структура",
                "company", "организация", "фирма"),
    "post":    ("должность", "position", "post", "appointment", "профессия"),
    "code":    ("код", "кодключа", "code", "codep", "ключ", "идентификатор",
                "card", "cardcode", "wiegand", "wiegand26", "пропуск",
                "кодкарты", "идентификатордоступа"),
    "level":   ("уровеньдоступа", "уровень", "accesslevel", "access",
                "доступ", "полномочия"),
    "finish":  ("срокдействия", "срок", "finish", "действуетдо",
                "датаокончания", "окончание", "validuntil",
                "dateend", "enddate", "датадо"),
    "phone":   ("телефон", "phone", "тел", "tel", "mobile"),
    "note":    ("примечание", "комментарий", "note", "comment", "описание"),
    "photo":   ("фото", "photo", "picture", "image", "изображение", "фотография"),
}
RU = {"fio": "ФИО", "surname": "Фамилия", "first": "Имя", "middle": "Отчество",
      "tab": "Табельный номер", "dept": "Отдел", "post": "Должность",
      "code": "Код карты", "level": "Уровень доступа", "finish": "Срок действия",
      "phone": "Телефон", "note": "Примечание", "photo": "Фото"}

# Русские имена для колонок выгрузки Ориона, у которых в Sigur нет
# стандартного поля. Файл импорта получит столбцы с этими названиями —
# создай в Sigur дополнительные поля персонала с ТАКИМИ ЖЕ названиями
# («Файл» → «Настройки» → «Персонал»), и в окне импорта их будет легко
# связать. Незнакомые колонки остаются под своим исходным именем.
FIELD_RU = {
    "birthdate": "Дата рождения",
    "дата рождения": "Дата рождения",
    "address": "Прописка",
    "адрес": "Прописка",
    "pasportn": "Паспорт РФ",
    "pasportnum": "Паспорт РФ",
    "passportn": "Паспорт РФ",
    "паспорт": "Паспорт РФ",
    "dokumn": "Паспорт РФ",
    "dokumnumber": "Паспорт РФ",
    "dokumnos": "Паспорт РФ",
    "pasportdate": "Дата выдачи паспорта",
    "паспортдата": "Дата выдачи паспорта",
    "dokumdate": "Дата выдачи паспорта",
    "pasportkem": "Кем выдан паспорт",
    "pasportaddress": "Адрес регистрации",
    "datedocument": "Дата выдачи паспорта",
    "документдата": "Дата выдачи паспорта",
    "kodpodr": "Код подразделения (паспорт)",
    "kem": "Кем выдан паспорт",
    "datebirth": "Дата рождения",
    "level": "Уровень доступа",
    "уровеньдоступа": "Уровень доступа",
    "email": "Электронная почта",
    "company": "Компания",
    "organization": "Компания",
    "section": "Подразделение",
    "подразделение": "Подразделение",
    "dateend": "Действует до",
    "действуетдо": "Действует до",
    "enddate": "Действует до",
    "finish": "Действует до",
    "start": "Действует с (Орион)",
}


# Служебные поля базы «Орион Про» — внутренние коды записи (статус, график,
# время изменения, кто создал и т.п.). Человеку в Sigur не нужны, поэтому
# в «Примечание» и доп. столбцы НЕ попадают (в исходном файле остаются).
JUNK_COLS = {
    "id", "uid", "rowid", "guid", "guid1c",
    "status", "статус",
    "shedule", "schedule", "график",
    "spack",
    "grstatus",
    "changetime", "changrtime", "времяизменения",
    "indexforcontactid",
    "statuslist",
    "gtype",
    "config",
    "owner", "ownerid", "ownername",
    # "start" убран из мусора: это «Дата и время начала» из графы
    # «ПЕРИОД ДЕЙСТВИЯ КЛЮЧА» Болид — идёт доп. столбцом
    # «Действует с (Орион)»
    "operatorid",
    "workstation", "workstatiin",
    "timeofcreation",
    "fingerprint",
    "picture",
    "typedocum", "sexguest", "dokumseries",
    "gtypecodeadd", "groupid",
    "codepadd",   # постоянное доп. значение ключа (FE01) — информации не несёт
}


def is_junk(header):
    """Служебное поле базы Ориона? (сравнение без пробелов и регистра)"""
    return re.sub(r"[^a-zа-яё0-9]", "", str(header).lower()) in JUNK_COLS


def ru_name(h):
    """Русское имя для колонки выгрузки (или исходное, если неизвестна)."""
    s = str(h).strip().lower()
    if s in FIELD_RU:
        return FIELD_RU[s]
    return FIELD_RU.get(norm(s), str(h))


def norm(s):
    return re.sub(r"[^a-zа-яё0-9]", "", (s or "").strip().lower())


def auto_map(headers):
    hs = [(i, norm(h)) for i, h in enumerate(headers)]
    m = {}
    for key, al in ALIASES.items():
        hit = None
        for a in al:
            for i, h in hs:
                if h == a:
                    hit = i
                    break
            if hit is not None:
                break
        if hit is None:
            for a in al:
                for i, h in hs:
                    if h.startswith(a) or a in h:
                        hit = i
                        break
                if hit is not None:
                    break
        m[key] = hit
    return m


# ============================================================ сборка
def build_rows(headers, rows, mapping):
    """-> (люди, проблемы, уровни)"""
    def g(r, k):
        i = mapping.get(k)
        return r[i].strip() if i is not None and i < len(r) else ""

    used = {i for i in mapping.values() if i is not None}

    def extras(r):
        """Данные колонок, не назначенных ни одному полю -> пары (имя, значение).
        Имя берётся русское (FIELD_RU) — под названия доп. полей Sigur.
        Служебные поля Ориона (Status, Schedule, ChangeTime...) пропускаем."""
        out = []
        for i, h in enumerate(headers):
            if i in used or i >= len(r) or is_junk(h):
                continue
            v = str(r[i]).strip()
            if v and v.lower() not in ("none", "null"):
                out.append((ru_name(h), v))
        return out

    people, problems, levels = {}, [], []
    last_key = None
    for n, row in enumerate(rows, start=2):
        if not any(str(x).strip() for x in row if x is not None):
            continue                                   # полностью пустая строка
        raw = g(row, "code")
        code, how = parse_code(raw)
        tab = g(row, "tab")

        if mapping.get("fio") is not None:
            fio_raw = g(row, "fio")
        else:
            fio_raw = " ".join(x for x in (g(row, "surname"), g(row, "first"), g(row, "middle")) if x)
        dept = re.sub(r"\s+", " ", g(row, "dept")).strip()

        if not fio_raw.strip() and not tab and not dept and last_key is not None:
            # строка-продолжение: карта (и срок) — относим к прошлому человеку.
            # Код мог не конвертироваться (старая карта) — строка всё равно
            # его: помечаем карту проблемой, но человека не создаём.
            if code:
                people[last_key]["codes"].append((code, norm_date(g(row, "finish"))))
            elif raw:
                problems.append((n, people[last_key]["fio"], raw,
                                 how + " (строка-продолжение)"))
            continue

        fio = re.sub(r"\s+", " ", fio_raw).strip() or f"Строка {n}"
        key = (tab, fio, dept) if tab else (fio, dept)
        last_key = key
        first = key not in people
        p = people.setdefault(key, {
            "fio": fio, "dept": dept, "post": g(row, "post"), "tab": tab,
            "phone": g(row, "phone"), "note": g(row, "note"),
            "codes": [], "photo": g(row, "photo"),
            "extra": "", "extra_pairs": [], "key_notes": [],
        })
        if first:
            p["extra_pairs"] = extras(row)
            # каждое поле — с новой строки (так читабельнее в карточке Sigur)
            p["extra"] = "\n".join(f"{h}: {v}" for h, v in p["extra_pairs"])
            # в «Примечание» Sigur пишем ТОЛЬКО дату рождения;
            # остальное — отдельными столбцами (доп. параметры)
            p["birth_line"] = ""
            for i, h in enumerate(headers):
                hn = norm(h)
                if ("birth" in hn or "рожден" in hn) and i < len(row) \
                        and i not in used and not is_junk(h):
                    v = str(row[i]).strip()
                    if v and v.lower() not in ("none", "null"):
                        p["birth_line"] = f"Дата рождения: {norm_date(v) or v}"
                        break
        if code:
            p["codes"].append((code, norm_date(g(row, "finish"))))
            if not first:
                known = set(p["extra_pairs"])
                ex = [x for x in extras(row) if x not in known]
                if ex:
                    p["key_notes"].append(
                        f"карта {code}: " + "; ".join(f"{h}: {v}" for h, v in ex))
        else:
            problems.append((n, fio, raw, how))
        if g(row, "level"):
            levels.append((fio, dept, g(row, "level"), code or ""))
    return people, problems, levels


def ensure_xlwt(log=None):
    """Готов ли компонент для записи .xls; при необходимости ставим сами."""
    try:
        import xlwt  # noqa: F401
        return True
    except Exception:
        pass
    import subprocess
    try:
        if log:
            log("Не хватает компонента xlwt — устанавливаю (нужен интернет)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "xlwt"],
                       capture_output=True, timeout=300)
        import xlwt  # noqa: F401
        if log:
            log("Компонент установлен — продолжаю.")
        return True
    except Exception as ex:
        if log:
            log(f"Установить не удалось: {ex}")
        return False


def write_sigur(people, out_xls, out_dir, src_dir="", to_note=True, to_cols=True):
    import xlwt
    # wrap on — чтобы многострочные примечания были видны и в самом Excel
    TXT = xlwt.easyxf("align: wrap on, vert top", num_format_str="@")
    HDR = xlwt.easyxf("font: bold on; pattern: pattern solid, fore_colour 0x16",
                      num_format_str="@")
    cols = ["ФИО", "Отдел", "Должность", "Номер пропуска", "Срок действия",
            "Табельный номер", "Номер телефона", "Тип записи",
            "Имя файла фотографии", "Примечание"]

    # дополнительные столбцы — прочие данные карточки из «Ориона» (адрес,
    # паспорт, дата рождения...). В Sigur создаются дополнительные поля
    # персонала с такими же названиями («Файл» → «Настройки» → «Персонал»),
    # и при импорте каждый столбец привязывается к своему полю.
    extra_cols = []
    if to_cols:
        for p in people.values():
            for h, _v in p.get("extra_pairs", []):
                if h not in extra_cols:
                    extra_cols.append(h)

    wb = xlwt.Workbook(encoding="utf-8")
    ws = wb.add_sheet("Импорт", cell_overwrite_ok=True)
    widths = (9000, 8000, 8000, 6000, 5500, 6000, 6000, 5000, 8000, 9000)
    for i, h in enumerate(cols + extra_cols):
        ws.write(0, i, h, HDR)
        ws.col(i).width = widths[i] if i < len(widths) else 6500

    photo_dir = os.path.join(out_dir, "Фотографии")   # имя папки — как ищет Sigur
    os.makedirs(photo_dir, exist_ok=True)
    nphoto = 0
    r = 1
    for p in people.values():
        photo = ""
        if p.get("photo"):
            fn = extract_photo(p["photo"], photo_dir, p["tab"] or p["fio"], src_dir)
            if fn:
                # Sigur ищет относительный путь во вложенной папке рядом с таблицей
                photo = "Фотографии\\" + fn
                nphoto += 1
        # примечание = ТОЛЬКО дата рождения (просьба от 29.09);
        # паспорт, прописка и прочее идут отдельными столбцами (доп. поля Sigur)
        note = (p.get("birth_line") or "") if to_note else ""
        ev = dict(p.get("extra_pairs", []))
        codes = p["codes"] or [("", "")]
        for j, (code, fin) in enumerate(codes[:5]):
            vals = ([p["fio"], p["dept"], p["post"], code, fin, p["tab"],
                     p["phone"], "Сотрудник", photo, note]
                    + [ev.get(h, "") for h in extra_cols]) if j == 0 \
                else (["", "", "", code, fin, "", "", "", "", ""]
                      + [""] * len(extra_cols))
            for i, v in enumerate(vals):
                ws.write(r, i, v, TXT)
            r += 1
    wb.save(out_xls)
    if not os.listdir(photo_dir):
        os.rmdir(photo_dir)
    return r - 1, nphoto


# ============================================================ GUI
def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title(f"{APP}  v{VER}")
    root.geometry("1020x760")

    st = {"headers": [], "rows": [], "info": "", "mapping": {}, "src": ""}

    def log(s):
        txt_log.configure(state="normal")
        txt_log.insert("end", s + "\n")
        txt_log.see("end")
        txt_log.configure(state="disabled")
        root.update_idletasks()

    # --- верхняя панель
    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="1. Файл из «Орион Про»:").grid(row=0, column=0, sticky="w")
    e_src = ttk.Entry(top, width=70)
    e_src.grid(row=0, column=1, padx=6, sticky="ew")
    ttk.Button(top, text="Обзор…", command=lambda: pick_src()).grid(row=0, column=2)

    ttk.Label(top, text="2. Куда сохранить:").grid(row=1, column=0, sticky="w", pady=(8, 0))
    e_out = ttk.Entry(top, width=70)
    e_out.grid(row=1, column=1, padx=6, pady=(8, 0), sticky="ew")
    ttk.Button(top, text="Обзор…", command=lambda: pick_out()).grid(row=1, column=2, pady=(8, 0))

    ttk.Label(top, text="3. Формат карт:").grid(row=2, column=0, sticky="w", pady=(8, 0))
    cb_fmt = ttk.Combobox(top, width=24, state="readonly",
                          values=["W34 (наши карты)", "W26"])
    cb_fmt.set("W34 (наши карты)")
    cb_fmt.grid(row=2, column=1, padx=6, pady=(8, 0), sticky="w")
    ttk.Label(top, text="какой формат выдают считыватели (виден в событиях Sigur)",
              foreground="#5a6a7e").grid(row=2, column=2, pady=(8, 0), sticky="w")
    ttk.Label(top, text="4. Номер своей карты:").grid(row=3, column=0, sticky="w", pady=(8, 0))
    e_known = ttk.Entry(top, width=24)
    e_known.grid(row=3, column=1, padx=6, pady=(8, 0), sticky="w")
    ttk.Label(top, text="как его показывает Sigur при поднесении, напр. A1B2C3D4 —\nпо нему программа проверит правило «8 знаков до 01»; без сверки\nоно всё равно применяется, но сверь хотя бы одну карту",
              foreground="#5a6a7e", justify="left").grid(row=3, column=2, pady=(8, 0), sticky="w")
    var_cols = tk.BooleanVar(value=True)
    ttk.Checkbutton(top, variable=var_cols,
                    text="Прочие данные — отдельными столбцами (для доп. полей Sigur,"
                         " если создаёшь)"
                    ).grid(row=4, column=1, sticky="w", pady=(6, 0))
    var_note = tk.BooleanVar(value=True)
    ttk.Checkbutton(top, variable=var_note,
                    text="В «Примечание» писать дату рождения (паспорт, прописка"
                         " и прочее — отдельными столбцами для доп. полей)"
                    ).grid(row=5, column=1, sticky="w", pady=(2, 0))
    top.columnconfigure(1, weight=1)

    def sync_format():
        global CARD_FORMAT
        CARD_FORMAT = "W34" if cb_fmt.get().startswith("W34") else "W26"

    def pick_src():
        p = filedialog.askopenfilename(
            title="Файл, выгруженный из «Орион Про»",
            filetypes=[("Выгрузка Болид", "*.csv *.xml *.xls *.xlsx *.txt"),
                       ("Все файлы", "*.*")])
        if not p:
            return
        e_src.delete(0, "end")
        e_src.insert(0, p)
        if not e_out.get():
            e_out.delete(0, "end")
            e_out.insert(0, os.path.dirname(p))
        do_parse()

    def pick_out():
        p = filedialog.askdirectory(title="Куда сохранить результат")
        if p:
            e_out.delete(0, "end")
            e_out.insert(0, p)

    # --- сопоставление колонок
    box_map = ttk.LabelFrame(root, text="Сопоставление колонок (поправьте, если программа ошиблась)", padding=8)
    box_map.pack(fill="x", padx=8, pady=6)
    combos = {}
    keys = ["surname", "first", "middle", "tab", "dept", "post", "code",
            "level", "finish", "phone", "note", "photo"]
    for i, k in enumerate(keys):
        ttk.Label(box_map, text=RU[k]).grid(row=i // 4, column=(i % 4) * 2, sticky="w", padx=(0, 4), pady=2)
        c = ttk.Combobox(box_map, width=24, state="readonly")
        c.grid(row=i // 4, column=(i % 4) * 2 + 1, padx=(0, 14), pady=2)
        c.set("— не используется —")
        combos[k] = c

    def do_parse():
        sync_format()
        p = e_src.get().strip()
        if not p or not os.path.isfile(p):
            return
        try:
            headers, rows, info = read_any(p)
        except Exception as ex:
            messagebox.showerror("Ошибка чтения", f"{ex}")
            return
        st.update(headers=headers, rows=rows, info=info, src=p)
        m = auto_map(headers)
        m, date_col = detect_date_col(headers, rows, m)
        st["mapping"] = m
        opts = ["— не используется —"] + list(headers)
        for k, c in combos.items():
            c["values"] = opts
            idx = m.get(k)
            c.set(headers[idx] if idx is not None and idx < len(headers) else opts[0])
        ncode = sum(1 for r in rows if parse_code(r[m["code"]] if m.get("code") is not None and m["code"] < len(r) else "")[0])
        log(f"Прочитано: {info}")
        log(f"Строк: {len(rows)}. Колонок: {len(headers)}.")
        log("Колонки: " + ", ".join(headers[:14]) + ("…" if len(headers) > 14 else ""))
        log(f"Кодов карт распознано: {ncode}")
        if m.get("code") is None:
            log("ВНИМАНИЕ: не нашёл колонку с кодом карты — выберите её вручную!")
        if m.get("photo") is not None:
            log("Нашёл колонку с фотографиями.")
        if date_col:
            log(f"Колонка «{date_col}» похожа на СРОК ДЕЙСТВИЯ — подключил её сам.")
            log("Если это не она — выберите нужную в строке «Срок действия».")
        elif m.get("finish") is None:
            log("Колонку со сроком действия не нашёл — если она есть, выберите")
            log("её вручную в строке «Срок действия».")
        show_preview()

    def cur_mapping():
        sync_format()
        m = {}
        for k, c in combos.items():
            v = c.get()
            m[k] = st["headers"].index(v) if v in st["headers"] else None
        return m

    def apply_fit(verbose=True):
        """Сверка правила вырезания номера по известной карте."""
        global FITTED_RULE, FIT_INFO
        FITTED_RULE, FIT_INFO = None, ""
        known = e_known.get().strip()
        if not known or not st["rows"] or not st["headers"]:
            return True          # сверки нет — не ошибка
        fmt = "W34" if cb_fmt.get().startswith("W34") else "W26"
        m = cur_mapping()
        ci = m.get("code")
        if ci is None:
            return True
        codes = [r[ci] for r in st["rows"] if ci < len(r) and str(r[ci]).strip()]
        rule, rname, kn = fit_card_rule(known, codes, fmt)
        if rule:
            FITTED_RULE = rule
            FIT_INFO = f"{rname} — сверено по карте {kn}"
            if verbose:
                log(f"Сверка карт: правило подобрано ({rname}), карта {kn} найдена ✓")
            return True
        if verbose:
            log(f"Сверка карт: НЕ УДАЛОСЬ сопоставить «{known}» с кодами в файле.")
            log("Проверь, что номер написан точно как в Sigur, и что эта карта")
            log("есть в выгрузке. Если карты W34 — проверь, что в поле 3 выбрано W34.")
        return False

    def show_preview():
        apply_fit()
        for i in tree.get_children():
            tree.delete(i)
        m = cur_mapping()
        tree["columns"] = ("n", "fio", "dept", "post", "code", "sig")
        for h, w, a in (("n", 45, "center"), ("fio", 210, "w"), ("dept", 150, "w"),
                        ("post", 130, "w"), ("code", 150, "w"), ("sig", 110, "w")):
            tree.heading(h, text={"n": "№", "fio": "ФИО", "dept": "Отдел",
                                  "post": "Должность", "code": "Код (как было)",
                                  "sig": "В Sigur"}[h])
            tree.column(h, width=w, anchor=a)
        for n, row in enumerate(st["rows"][:300], start=1):
            def g(k):
                i = m.get(k)
                return row[i].strip() if i is not None and i < len(row) else ""
            fio = g("fio") or " ".join(x for x in (g("surname"), g("first"), g("middle")) if x)
            code, _ = parse_code(g("code"))
            tree.insert("", "end", values=(n, re.sub(r"\s+", " ", fio),
                                           g("dept"), g("post"), g("code"), code or "—"))

    box_prev = ttk.LabelFrame(root, text="Предпросмотр (первые 300 строк)", padding=6)
    box_prev.pack(fill="both", expand=True, padx=8)
    tree = ttk.Treeview(box_prev, show="headings", height=11)
    vs = ttk.Scrollbar(box_prev, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vs.set)
    tree.pack(side="left", fill="both", expand=True)
    vs.pack(side="right", fill="y")

    # --- кнопки
    btns = ttk.Frame(root, padding=8)
    btns.pack(fill="x")
    ttk.Button(btns, text="Обновить предпросмотр", command=show_preview).pack(side="left")

    def do_export():
        if not st["rows"]:
            messagebox.showwarning("Пусто", "Сначала выберите файл выгрузки (кнопка «Обзор…» сверху).")
            return
        try:
            if not ensure_xlwt(log):
                messagebox.showerror(
                    "Не хватает компонента",
                    "Не удалось подготовить компонент для создания Excel-файла.\n\n"
                    "Запусти программу через Запустить_миграцию.bat —\n"
                    "он установит всё сам (нужен интернет, только первый раз).")
                return
            out = e_out.get().strip() or os.path.dirname(st["src"])
            os.makedirs(out, exist_ok=True)
            m = cur_mapping()
            ok_fit = apply_fit()
            if not ok_fit:
                if not messagebox.askyesno(
                        "Сверка не прошла",
                        "Программа не смогла сопоставить номер твоей карты\n"
                        "ни с одним кодом в файле.\n\n"
                        "Проверь, что в поле «4. Номер своей карты» номер написан\n"
                        "точно так, как его показывает Sigur (например, A1B2C3D4),\n"
                        "и что эта карта есть в выгрузке.\n\n"
                        "Продолжить без сверки?"):
                    return
            people, problems, levels = build_rows(st["headers"], st["rows"], m)
            xls = os.path.join(out, "Импорт_для_Sigur.xls")
            try:
                nrows, nphoto = write_sigur(people, xls, out, os.path.dirname(st["src"]),
                                            var_note.get(), var_cols.get())
            except PermissionError as ex:
                raise RuntimeError(
                    "Какой-то файл оказался занят другим процессом.\n"
                    "Закрой Excel (Импорт_для_Sigur.xls) и программы просмотра\n"
                    "фотографий, затем нажми кнопку ещё раз.\n"
                    f"Технические детали: {ex}")
            rep = os.path.join(out, "Отчёт.txt")
            with open(rep, "w", encoding="utf-8") as f:
                f.write("ОТЧЁТ ПЕРЕНОСА «Орион Про» → Sigur\n" + "=" * 62 + "\n\n")
                f.write(f"Исходный файл ....... {st['src']}\n")
                f.write(f"Формат .............. {st['info']}\n")
                f.write(f"Формат карт ......... {CARD_FORMAT}\n")
                if CARD_FORMAT == "W34":
                    if FIT_INFO:
                        f.write(f"Правило номеров ..... {FIT_INFO} ✓\n")
                    else:
                        f.write("Правило номеров ..... 8 знаков до 01 в конце кода Болид \n")
                        f.write("(сверка по своей карте не проводилась)\n")
                        f.write("Номер своей карты (поле 4) лучше вписать и переделать файл — \n")
                        f.write("тогда правило будет проверено по настоящей карте.\n")
                f.write(f"Строк ............... {len(st['rows'])}\n")
                f.write(f"Сотрудников ......... {len(people)}\n")
                f.write(f"Кодов карт .......... {sum(len(p['codes']) for p in people.values())}\n")
                f.write(f"Фотографий .......... {nphoto}\n")
                fin_col = st["headers"][m["finish"]] if m.get("finish") is not None and m["finish"] < len(st["headers"]) else None
                f.write(f"Срок действия ....... " + (f"колонка «{fin_col}»" if fin_col else "НЕ найден") + "\n")
                f.write(f"Прочие данные ....... отдельные столбцы: "
                        + ("да" if var_cols.get() else "нет")
                        + ", в «Примечание»: "
                        + ("только дата рождения" if var_note.get() else "нет") + "\n")
                f.write(f"Не распознано ....... {len(problems)}\n\n")
                if problems:
                    f.write("НЕ РАСПОЗНАНО:\n")
                    for n, fio, raw, how in problems[:60]:
                        f.write(f"  строка {n}: {fio} | «{raw}» | {how}\n")
            if levels:
                with open(os.path.join(out, "Уровни_доступа.csv"), "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.writer(f, delimiter=";")
                    w.writerow(["ФИО", "Отдел", "Уровень доступа", "Код карты"])
                    w.writerows(levels)

            log("=" * 50)
            log(f"ГОТОВО: {xls}")
            log(f"  сотрудников: {len(people)}, строк: {nrows}, фото: {nphoto}")
            log(f"  отчёт: {rep}")
            if CARD_FORMAT == "W34":
                if FIT_INFO:
                    log(f"Правило номеров: {FIT_INFO} ✓")
                else:
                    log("Правило номеров: 8 знаков до 01 в конце кода Болид (без сверки)")
            messagebox.showinfo(
                "Готово",
                f"Файл для Sigur создан:\n{xls}\n\n"
                f"Сотрудников: {len(people)}\nФотографий: {nphoto}\n\n"
                + ("Папку «Фото» (рядом с файлом) не перемещай и не удаляй до конца импорта в Sigur.\n\n"
                   if nphoto else "")
                + "Рядом лежит Отчёт.txt — обязательно прочитай.")
        except Exception as ex:
            err = traceback.format_exc()
            try:
                open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ошибка.txt"),
                     "w", encoding="utf-8").write(err)
            except Exception:
                pass
            log(f"ОШИБКА: {ex}")
            messagebox.showerror(
                "Не получилось",
                f"{ex}\n\nПодробности сохранены в файл ошибка.txt (рядом с программой)\n"
                "— пришли его мне, и я скажу, в чём дело.")

    def do_diag():
        if not st["headers"]:
            return
        p = os.path.join(e_out.get().strip() or ".", "Диагностика.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"Файл: {st['src']}\nФормат: {st['info']}\n\n")
            f.write("КОЛОНКИ:\n")
            for i, h in enumerate(st["headers"]):
                f.write(f"  [{i}] {h}\n")
            f.write("\nПЕРВЫЕ 3 СТРОКИ:\n")
            for r in st["rows"][:3]:
                f.write("  " + " | ".join(r[:20]) + "\n")
        log(f"Диагностика сохранена: {p} — пришлите этот файл, если что-то не так.")
        messagebox.showinfo("Диагностика", f"Сохранено:\n{p}\n\nПришлите этот файл, если программа что-то не поняла.")

    ttk.Button(btns, text="Диагностика (если не разобралось)", command=do_diag).pack(side="left", padx=8)
    ttk.Button(btns, text="СДЕЛАТЬ ФАЙЛ ДЛЯ SIGUR",
               command=do_export).pack(side="right")

    # --- лог
    box_log = ttk.LabelFrame(root, text="Сообщения", padding=6)
    box_log.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    txt_log = tk.Text(box_log, height=8, wrap="word", state="disabled")
    txt_log.pack(fill="both", expand=True)

    log(f"{APP} v{VER}")
    log("Выберите файл, выгруженный из «Орион Про» — программа примет csv, xml, xls или xlsx.")
    try:
        import xlwt  # noqa: F401
        log("Компонент для создания Excel-файла: на месте.")
    except Exception:
        log("ВНИМАНИЕ: не хватает компонента для создания Excel. Кнопка попытается")
        log("установить его сама (нужен интернет), но надёжнее запустить программу")
        log("через Запустить_миграцию.bat — он ставит всё автоматически.")
    root.mainloop()


if __name__ == "__main__":
    try:
        run_gui()
    except Exception:
        err = traceback.format_exc()
        try:
            open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ошибка.txt"),
                 "w", encoding="utf-8").write(err)
        except Exception:
            pass
        try:
            import tkinter.messagebox as mb
            import tkinter as tk
            tk.Tk().withdraw()
            mb.showerror("Ошибка", "Что-то пошло не так. Подробности — в файле ошибка.txt\n\n" + err[-900:])
        except Exception:
            print(err)
        sys.exit(1)
