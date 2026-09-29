#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ПОЛНАЯ ВЫГРУЗКА ИЗ БАЗЫ «ОРИОН ПРО» (БОЛИД): ЛЮДИ + КЛЮЧИ/КАРТЫ + ФОТОГРАФИИ

Запускается на компьютере, где стоит «Орион Про» с базой MS SQL.
Читает данные прямо из базы и складывает их в файлы, которые понимает
программа «Миграция Болид → Sigur»:

    Болид_выгрузка.csv   — люди, все их данные и ВСЕ коды карт
    Фотографии\          — фотографии сотрудников (файлы)
    Отчёт_выгрузки.txt   — что и сколько выгрузилось

ВАЖНО: база только ЧИТАЕТСЯ (SELECT). Программа ничего в ней не меняет
и не пишет. Работающая «Орион Про» этому не мешает.
"""
import os, re, sys, csv, traceback

APP = "Полная выгрузка из базы «Орион Про»"
VER = "v.01"

# ============================================================ поиск MS SQL
def parse_services(text):
    """Разбор вывода `sc query` — ищем службы MS SQL и PostgreSQL."""
    servers, postgres = [], False
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("service_name:"):
            name = line.split(":", 1)[1].strip()
            l = name.lower()
            if l.startswith("mssql$"):
                servers.append("localhost\\" + name.split("$", 1)[1])
            elif l == "mssqlserver":
                servers.append("localhost")
            elif "postgres" in l:
                postgres = True
    return servers, postgres


def find_sql_instances():
    import subprocess
    try:
        raw = subprocess.run(["sc", "query", "type=", "service", "state=", "all"],
                             capture_output=True, timeout=30).stdout
        return parse_services(raw.decode("cp866", "ignore"))
    except Exception:
        return [], False


def registry_instances():
    """Имена установленных SQL Server из реестра Windows."""
    found = []
    try:
        import winreg
    except ImportError:
        return found
    for path in (r"SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL",
                 r"SOFTWARE\WOW6432Node\Microsoft\Microsoft SQL Server\Instance Names\SQL"):
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        except OSError:
            continue
        i = 0
        while True:
            try:
                name, val, _ = winreg.EnumValue(key, i)
            except OSError:
                break
            found.append((name, val))
            i += 1
    return found


def collect_servers(manual=None):
    """Все кандидаты в SQL-серверы на этом компьютере (порядок — по приоритету).

    Человеку не нужно знать имя сервера: переберём всё, что найдём."""
    out, seen = [], set()

    def add(s):
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    if manual:
        add(manual.strip())
    svc, _pg = find_sql_instances()
    for s in svc:
        add(s)
    for name, _val in registry_instances():
        add("localhost" if name.upper() == "MSSQLSERVER" else "localhost\\" + name)
    add("localhost\\SQLEXPRESS")
    add("localhost")
    cn = os.environ.get("COMPUTERNAME", "")
    if cn:
        add(cn)
        add(cn + "\\SQLEXPRESS")
    return out


# ============================================================ работа с SQL
def qi(x):
    return "[" + str(x).replace("]", "]]") + "]"


def fmt_val(v):
    """Значение для CSV: даты — в виде ДД.ММ.ГГГГ, байты — HEX-кодом."""
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        return v.strftime("%d.%m.%Y")
    if isinstance(v, (bytes, bytearray)):
        return v.hex().upper()
    return v


def host_is_local(server):
    """Сервер находится на этом же компьютере?"""
    host = str(server).split("\\")[0].strip().lower()
    if host in ("localhost", "(local)", ".", "127.0.0.1"):
        return True
    cn = os.environ.get("COMPUTERNAME", "").lower()
    return bool(cn) and host == cn


def server_variants(server):
    """Варианты адреса одного сервера: как написан + внутренний канал «lpc:».

    «Орион» обычно стоит на одном компьютере с SQL и ходит в базу через
    внутренний канал без сети. Обычное сетевое подключение к локальному
    SQL часто закрыто (ошибка 08001) — поэтому пробуем оба варианта."""
    if not server:
        return []
    if re.match(r"^(lpc|np|tcp):", server, re.I):
        return [server]
    lpc = "lpc:" + server
    # для локального сервера внутренний канал пробуем первым
    return [lpc, server] if host_is_local(server) else [server, lpc]


def connect(server, db="master", user=None, pwd=None):
    """Подключение к MS SQL: перебираем все драйверы и оба варианта адреса.

    На новых Windows (11, Server 2025) старый драйвер «SQL Server» удалён —
    там работают только «ODBC Driver 17/18 for SQL Server». Пробуем всё.
    """
    if not server:
        raise RuntimeError("Не указан сервер MS SQL")
    import pyodbc
    last = None
    for srv in server_variants(server):
        for drv in sql_drivers():
            cs = f"DRIVER={{{drv}}};SERVER={srv};DATABASE={db};"
            if user:
                cs += f"UID={user};PWD={pwd};"
            else:
                cs += "Trusted_Connection=yes;"
            if "ODBC Driver 1" in drv:
                # новые драйверы шифруют соединение по умолчанию — отключаем,
                # иначе старые SQL-серверы отказывают в подключении
                cs += "Encrypt=no;TrustServerCertificate=yes;"
            try:
                return pyodbc.connect(cs, timeout=8)
            except Exception as ex:
                last = ex
    raise last


def sql_drivers():
    """Доступные ODBC-драйверы для MS SQL, в порядке предпочтения."""
    try:
        import pyodbc
        ds = list(pyodbc.drivers())
    except Exception:
        return ["SQL Server"]
    prio = ["SQL Server", "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server", "ODBC Driver 13 for SQL Server",
            "SQL Server Native Client 11.0", "SQL Server Native Client 10.0"]
    found = [d for d in prio if d in ds]
    found += [d for d in ds if d not in found and "SQL" in d.upper()]
    return found or ["SQL Server"]


def table_cols(cur, db, table):
    """{имя колонки: тип} для таблицы. Пусто, если таблицы нет."""
    rows = cur.execute(
        f"SELECT COLUMN_NAME, DATA_TYPE FROM {qi(db)}.INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_NAME = ?", table).fetchall()
    return {r[0]: r[1] for r in rows}


def find_orion_dbs(conn):
    """Список баз на сервере, в которых есть pList и pMark."""
    cur = conn.cursor()
    dbs = [r[0] for r in cur.execute(
        "SELECT name FROM sys.databases "
        "WHERE database_id NOT IN (1,2,3,4) AND state_desc = 'ONLINE'").fetchall()]
    found = []
    for db in dbs:
        try:
            n = cur.execute(
                f"SELECT COUNT(*) FROM {qi(db)}.INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_NAME IN ('pList','pMark')").fetchone()[0]
            if n == 2:
                try:
                    people = cur.execute(f"SELECT COUNT(*) FROM {qi(db)}.dbo.pList").fetchone()[0]
                except Exception:
                    people = -1
                found.append((db, people))
        except Exception:
            pass
    return found


def pick(cols, names):
    low = {k.lower(): k for k in cols}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


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


def photo_to_file(value, photo_dir, base):
    """Сохраняет фото из значения БД (байты / base64 / hex / путь) -> имя файла."""
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
        if len(data) < 60 or not sniff_ext(data):
            return ""
        fn = safe_name(base) + sniff_ext(data)
        open(os.path.join(photo_dir, fn), "wb").write(data)
        return fn
    s = str(value).strip()
    if len(s) < 8:
        return ""
    if len(s) < 400 and os.path.isfile(s):
        import shutil
        ext = os.path.splitext(s)[1] or ".jpg"
        fn = safe_name(base) + ext
        shutil.copy2(s, os.path.join(photo_dir, fn))
        return fn
    if len(s) > 100 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", s):
        import base64
        try:
            data = base64.b64decode(re.sub(r"\s", "", s))
        except Exception:
            data = b""
        if sniff_ext(data):
            fn = safe_name(base) + sniff_ext(data)
            open(os.path.join(photo_dir, fn), "wb").write(data)
            return fn
    if len(s) > 200 and len(s) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", s):
        try:
            data = bytes.fromhex(s)
        except Exception:
            data = b""
        if sniff_ext(data):
            fn = safe_name(base) + sniff_ext(data)
            open(os.path.join(photo_dir, fn), "wb").write(data)
            return fn
    return ""


# ============================================================ главная выгрузка
def do_export(server, db, user, pwd, outdir, log):
    """Возвращает (путь csv, статистика) или бросает исключение."""
    log(f"Подключаюсь к серверу {server}, база {db}...")
    conn = connect(server, db, user, pwd)
    cur = conn.cursor()
    log("Подключение удалось.")

    plist = table_cols(cur, db, "pList")
    pmark = table_cols(cur, db, "pMark")
    if not plist:
        raise RuntimeError("В базе нет таблицы pList — это точно база «Орион Про»?")

    tabs = pick(plist, ["TabNumber", "Tab", "Tabel"])
    sur  = pick(plist, ["Name", "SurName", "Family"])
    fir  = pick(plist, ["FirstName"])
    mid  = pick(plist, ["MidName", "MiddleName"])
    post = pick(plist, ["Post", "Position"])
    pic  = pick(plist, ["Picture", "Photo", "Foto", "Image"])
    comp = pick(plist, ["Company", "Firm"])
    sect = pick(plist, ["Section", "Department"])
    codep = pick(pmark, ["CodeP", "Code", "Kod", "Key", "KeyCode"])
    owner = pick(pmark, ["Owner", "OwnerID", "Person"])

    # --- ВСЕ остальные колонки карточки из pList: телефон, адрес, документы,
    #     дата рождения — всё, что есть в базе «Ориона» (кроме служебных)
    BAD_TYPES = ("image", "varbinary", "binary", "timestamp", "uniqueidentifier")
    used_pl = {c for c in (tabs, sur, fir, mid, post, comp, sect, pic) if c}
    used_pl |= {"ID", "id", "GUID_1C", "GUID", "uid", "RowID"}
    # служебные поля Ориона (внутренние коды записи) — в файл не выгружаем
    JUNK = {re.sub(r"[^a-zа-яё0-9]", "", j.lower()) for j in (  # Start не мусор: дата начала действия ключа
        "ID", "GUID", "GUID_1C", "RowID", "uid",
        "Status", "Статус", "Shedule", "Schedule", "Spack", "Gr Status",
        "GrStatus", "Change time", "ChangeTime", "Changr time", "IndexForContactID",
        "Status list", "StatusList", "Gtype", "Config", "OwnerName",
        "Operator ID", "OperatorID", "Workstation", "Workstatiin",
        "TimeOfCreation", "Fingerprint", "Picture",
        "TypeDocum", "SexGuest", "DokumSeries", "GTypeCodeAdd", "GroupID",
        "CodePAdd")}   # CodePAdd = постоянная FE01, информации не несёт
    prest = [c for c, t in plist.items()
             if c not in used_pl and t not in BAD_TYPES
             and re.sub(r"[^a-zа-яё0-9]", "", c.lower()) not in JUNK][:20]
    log(f"Колонки pList: {', '.join(plist)}")
    log(f"Колонки pMark: {', '.join(pmark)}")
    if not sur:
        raise RuntimeError("Не нашёл колонку фамилии в pList — пришлите Диагностику.")
    if not codep:
        raise RuntimeError("Не нашёл колонку кодов (CodeP) в pMark — пришлите Диагностику.")
    if not owner:
        raise RuntimeError("Не нашёл колонку связи (Owner) в pMark — пришлите Диагностику.")

    # --- имена организаций/подразделений/должностей по справочникам Ориона.
    #     В базе «Орион Про» это таблицы PCompany / PDivision / PPost,
    #     а в pList.Company / pList.Section / pList.Post лежат НОМЕРА (ID).
    def name_expr(col, tables, alias):
        """SQL-выражение: имя по справочнику, иначе исходное значение (если это не номер)."""
        if not col:
            return "NULL", "", None
        for t in tables:
            tc = table_cols(cur, db, t)
            if not tc:
                continue
            tid = pick(tc, ["ID", "id", "Id"])
            tnm = pick(tc, ["Name", "NAME", "name"])
            if tid and tnm:
                # В колонке может лежать и ТЕКСТ («Гр.пом.»), и номер. Сравниваем
                # строками: CAST текста в int ронял весь запрос (ошибка 245).
                val = f"RTRIM(LTRIM(CAST(p.{qi(col)} AS nvarchar(200))))"
                num = f"{val} NOT LIKE '%[^0-9]%'"
                join = (f" LEFT JOIN {qi(t)} {alias} ON "
                        f"CASE WHEN {num} THEN {val} END = "
                        f"CAST({alias}.{qi(tid)} AS nvarchar(200))")
                expr = (f"COALESCE({alias}.{qi(tnm)}, "
                        f"CASE WHEN p.{qi(col)} IS NULL OR {num} THEN NULL "
                        f"ELSE {val} END)")
                return expr, join, t
        # справочника не нашли — пропускаем только текстовые значения (имена)
        return (f"CASE WHEN p.{qi(col)} IS NULL OR p.{qi(col)} LIKE '%[^0-9]%' "
                f"THEN p.{qi(col)} ELSE NULL END", "", None)

    comp_expr, join1, comp_t = name_expr(
        comp, ["PCompany", "pCompany", "Company", "Firm"], "cn")
    sect_expr, join2, sect_t = name_expr(
        sect, ["PDivision", "pDivision", "Section", "pSection", "Department"], "sn")
    post_expr, join3, post_t = name_expr(
        post, ["PPost", "pPost", "Post", "Posts", "Position"], "pn")
    joins = join1 + join2 + join3
    log("Справочники: организации — " + (comp_t or "НЕ найдены")
        + "; подразделения — " + (sect_t or "НЕ найдены")
        + "; должности — " + (post_t or "НЕ найдены"))

    # --- дополнительные колонки pMark (для полноты и отладки)
    extra_all = [c for c in pmark if c not in (owner, codep)
                 and re.sub(r"[^a-zа-яё0-9]", "", c.lower()) not in JUNK]
    # колонки-даты (сроки действия ключей!) — в начало списка, чтобы лимит
    # количества колонок их не вытеснил
    _dt = ("date", "datetime", "datetime2", "smalldatetime")
    extra = ([c for c in extra_all if pmark.get(c) in _dt]
             + [c for c in extra_all if pmark.get(c) not in _dt])[:30]
    extra_sel = (", " + ", ".join(f"m.{qi(c)}" for c in extra)) if extra else ""
    pre_sel = (", " + ", ".join(f"p.{qi(c)}" for c in prest)) if prest else ""

    sql = (f"SELECT p.{qi(tabs)}, p.{qi(sur)}, "
           + (f"p.{qi(fir)}, " if fir else "NULL, ")
           + (f"p.{qi(mid)}, " if mid else "NULL, ")
           + (f"{post_expr}, " if post else "NULL, ")
           + f"{comp_expr} AS _COMP, {sect_expr} AS _SECT, "
           + f"CAST(m.{qi(codep)} AS VARBINARY(200)) AS _CODE"
           + pre_sel
           + extra_sel
           + f" FROM pList p LEFT JOIN pMark m ON m.{qi(owner)} = p.ID{joins}")
    log("Читаю людей и ключи...")
    rows = cur.execute(sql).fetchall()
    log(f"Прочитано строк: {len(rows)}")

    # --- проверка: не потерялись ли должность/организация/подразделение.
    #     Если справочник не найден, а в pList лежат номера — SQL превращает
    #     их в пустоту; тогда предупреждаем (названия взять неоткуда).
    warn = []
    for idx, title, found, col in ((4, "Должность", post_t, post),
                                   (5, "Организация", comp_t, comp),
                                   (6, "Подразделение", sect_t, sect)):
        if col and not found:
            vals = [r[idx] for r in rows if r[idx] is not None and str(r[idx]).strip()]
            if not vals:
                warn.append(title)
    if warn:
        log("ВНИМАНИЕ: названия потеряны (" + ", ".join(warn)
            + ") — в базе номера, а справочник-таблица не найдена."
            " Пришлите Отчёт_выгрузки.txt")

    # --- фотографии
    os.makedirs(outdir, exist_ok=True)
    photo_dir = os.path.join(outdir, "Фотографии")   # имя папки — как ищет Sigur
    os.makedirs(photo_dir, exist_ok=True)
    photos = {}
    if pic:
        log("Читаю фотографии...")
        pcur = conn.cursor()
        pcur.execute(f"SELECT p.{qi(tabs)}, p.{qi(sur)}, "
                     + (f"p.{qi(fir)}, " if fir else "NULL, ")
                     + f"p.{qi(pic)} FROM pList p "
                     f"WHERE p.{qi(pic)} IS NOT NULL AND DATALENGTH(p.{qi(pic)}) > 0")
        ok = fail = 0
        for r in pcur.fetchall():
            tab = str(r[0]).strip() if r[0] is not None else ""
            fio = " ".join(str(x).strip() for x in (r[1], r[2]) if x and str(x).strip())
            base = tab or fio or "фото"
            fn = photo_to_file(r[3], photo_dir, base)
            if fn:
                # ключ — табельный номер, при его отсутствии — ФИО
                photos[tab if tab else fio.lower()] = "Фотографии\\" + fn
                ok += 1
            else:
                fail += 1
        log(f"Фотографий сохранено: {ok}" + (f", пропущено (не картинка): {fail}" if fail else ""))
    else:
        log("Колонки с фотографиями в базе не нашлось.")

    # --- CSV
    headers = ["Табельный номер", "Фамилия", "Имя", "Отчество", "Должность",
               "Отдел", "Код ключа", "Фото"] + prest + list(extra)
    csv_path = os.path.join(outdir, "Болид_выгрузка.csv")
    npeople, ncodes = set(), 0
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(headers)
        for r in rows:
            # порядок SELECT: 0 таб.№, 1 фамилия, 2 имя, 3 отчество, 4 должность,
            #   5 организация, 6 подразделение, 7 код ключа,
            #   8+ остальные данные карточки (pList) и ключа (pMark)
            tab = ("" if r[0] is None else str(r[0]).strip())
            fio = " ".join(str(x).strip() for x in (r[1], r[2], r[3]) if x and str(x).strip())
            npeople.add((tab, fio))
            code = r[7].hex().upper() if isinstance(r[7], (bytes, bytearray)) else ""
            ncodes += 1 if code else 0
            dept = ", ".join(str(x).strip() for x in (r[5], r[6]) if x and str(x).strip())
            photo = photos.get(tab, "") if tab else photos.get(fio.lower(), "")
            w.writerow([tab, r[1] or "", r[2] or "", r[3] or "", r[4] or "",
                        dept, code, photo] + [fmt_val(r[i]) for i in range(8, len(r))])
    log(f"Готово: {csv_path}")

    stats = {"rows": len(rows), "people": len(npeople), "codes": ncodes,
             "photos": len(photos), "csv": csv_path, "warn": warn}

    rep = os.path.join(outdir, "Отчёт_выгрузки.txt")
    with open(rep, "w", encoding="utf-8") as f:
        f.write("ОТЧЁТ ПОЛНОЙ ВЫГРУЗКИ ИЗ БАЗЫ «ОРИОН ПРО»\n" + "=" * 62 + "\n\n")
        f.write(f"Сервер ............... {server}\nБаза ................. {db}\n")
        f.write(f"Строк (люди × ключи) . {stats['rows']}\n")
        f.write(f"Разных людей .......... {stats['people']}\n")
        f.write(f"Ключей/карт с кодом ... {stats['codes']}\n")
        f.write(f"Фотографий ............ {stats['photos']}\n\n")
        if warn:
            f.write("ВНИМАНИЕ! Названия потеряны: " + ", ".join(warn) + "\n"
                    "(в базе лежат номера, а справочник-таблица не найдена).\n"
                    "Пришлите этот отчёт — добавим поддержку вашего справочника.\n\n")
        f.write("ДАЛЬШЕ:\n")
        f.write("  1. Запустите программу «Миграция Болид → Sigur» (Запустить_миграцию.bat)\n")
        f.write("  2. Выберите файл Болид_выгрузка.csv\n")
        f.write("  3. Проверьте предпросмотр и нажмите «СДЕЛАТЬ ФАЙЛ ДЛЯ SIGUR»\n")
    conn.close()
    return csv_path, stats


# ============================================================ диагностика
def do_diag(server, db, user, pwd, outpath, log):
    lines = [f"{APP} v{VER} — диагностика", ""]
    servers, postgres = find_sql_instances()
    lines.append(f"Найденные службы MS SQL: {servers or 'не найдены'}")
    if postgres:
        lines.append("!!! Обнаружена служба PostgreSQL — если «Орион Про» работает")
        lines.append("    на PostgreSQL, эта программа его не читает. Напишите мне.")
    lines.append(f"Сервер (из поля): {server or '—'}")
    lines.append(f"База (из поля):   {db or '—'}")
    try:
        import pyodbc  # noqa: F401
        drv_list = ", ".join(sql_drivers())
    except Exception:
        drv_list = "pyodbc не установлен (запустите программу через bat)"
    lines.append(f"Драйверы ODBC:    {drv_list}")
    lines.append("")

    # кандидаты: что вписано в поле + всё найденное на компьютере + типовые
    cands = collect_servers(server)

    lines.append(f"Пробую подключиться ({len(cands)} вариантов сервера, обычный адрес"
                 " и внутренний канал lpc:)...")
    for srv in cands:
        for variant in server_variants(srv):
            tag = variant if variant == srv else f"{variant}  (внутренний канал)"
            try:
                conn = connect(variant, "master", user, pwd)
            except Exception as ex:
                msg = str(ex).strip()
                msg = msg.splitlines()[0][:170] if msg else repr(ex)
                lines.append(f"  {tag}: ОШИБКА — {msg}")
                continue
            lines.append(f"  {tag}: ПОДКЛЮЧИЛОСЬ — ОК")
            try:
                cur = conn.cursor()
                dbs = [r[0] for r in cur.execute(
                    "SELECT name FROM sys.databases "
                    "WHERE database_id NOT IN (1,2,3,4)").fetchall()]
                lines.append(f"    Базы на сервере: {', '.join(dbs) or '—'}")
                for name, people in find_orion_dbs(conn):
                    cnt = f" ({people} чел.)" if people and people > 0 else ""
                    lines.append(f"    >>> база «Орион Про»: {name}{cnt}")
                if db:
                    for t in ("pList", "pMark"):
                        cols = table_cols(cur, db, t)
                        lines.append(f"    Колонки {t}: "
                                     + (", ".join(cols) if cols else "таблица не найдена"))
            except Exception as ex:
                lines.append(f"    (ошибка чтения: {ex})")
            conn.close()
            lines.append("")
            lines.append(f"ЧТО ВПИСАТЬ В ПРОГРАММУ: сервер = {variant}; "
                         f"база = {db or 'нажмите «НАЙТИ БАЗУ ОРИОНА» и выберите из списка'}")
            open(outpath, "w", encoding="utf-8").write("\n".join(lines))
            log(f"Диагностика сохранена: {outpath}")
            return
    lines.append("")
    lines.append("Подключиться не удалось ни одним способом. Пришлите этот файл мне —")
    lines.append("по нему я скажу точно, что делать.")
    open(outpath, "w", encoding="utf-8").write("\n".join(lines))
    log(f"Диагностика сохранена: {outpath}")


# ============================================================ GUI
def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title(f"{APP}  v{VER}")
    root.geometry("980x700")

    st = {"conn_ok": False, "dbs": []}

    def log(s):
        txt_log.configure(state="normal")
        txt_log.insert("end", s + "\n")
        txt_log.see("end")
        txt_log.configure(state="disabled")
        root.update_idletasks()

    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="Сервер MS SQL (необязательно):").grid(row=0, column=0, sticky="w")
    e_srv = ttk.Entry(top, width=40)
    e_srv.grid(row=0, column=1, padx=6, sticky="ew")
    ttk.Label(top, text="База данных:").grid(row=1, column=0, sticky="w", pady=(8, 0))
    # поле можно заполнить из списка (после поиска) ИЛИ вписать имя базы руками
    cb_db = ttk.Combobox(top, width=37)
    cb_db.grid(row=1, column=1, padx=6, pady=(8, 0), sticky="ew")

    auth = tk.StringVar(value="win")
    af = ttk.LabelFrame(top, text="Как подключаться к базе", padding=6)
    af.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
    ttk.Radiobutton(af, text="Windows-пользователь", variable=auth, value="win").pack(anchor="w")
    ttk.Radiobutton(af, text="Логин и пароль SQL (из окна «Параметры БД» Ориона)",
                    variable=auth, value="sql").pack(anchor="w")
    lf = ttk.Frame(af)
    lf.pack(anchor="w", pady=(4, 0))
    ttk.Label(lf, text="Логин:").pack(side="left")
    e_user = ttk.Entry(lf, width=18)
    e_user.pack(side="left", padx=(2, 10))
    ttk.Label(lf, text="Пароль:").pack(side="left")
    e_pwd = ttk.Entry(lf, width=18, show="*")
    e_pwd.pack(side="left", padx=2)
    # как только человек начинает вводить логин/пароль — сами включаем режим SQL
    e_user.bind("<Key>", lambda _e: auth.set("sql"))
    e_pwd.bind("<Key>", lambda _e: auth.set("sql"))
    ttk.Label(af, foreground="#666",
              text="значения — из «Орион Про»: Менеджер сервера → Сервис → Параметры БД"
              ).pack(anchor="w", pady=(3, 0))

    ttk.Label(top, text="Куда сохранить:").grid(row=3, column=0, sticky="w", pady=(10, 0))
    e_out = ttk.Entry(top, width=40)
    e_out.grid(row=3, column=1, padx=6, pady=(10, 0), sticky="ew")
    e_out.insert(0, os.path.dirname(os.path.abspath(__file__)))
    ttk.Button(top, text="Обзор…", command=lambda: pick_out()).grid(row=3, column=2, pady=(10, 0))
    top.columnconfigure(1, weight=1)

    def pick_out():
        p = filedialog.askdirectory(title="Куда сохранить выгрузку")
        if p:
            e_out.delete(0, "end")
            e_out.insert(0, p)

    def creds():
        return (e_user.get().strip(), e_pwd.get()) if auth.get() == "sql" else (None, None)

    btns = ttk.Frame(root, padding=8)
    btns.pack(fill="x")

    def do_find():
        _, postgres = find_sql_instances()
        if postgres:
            log("ОБНАРУЖЕН PostgreSQL. Если ваш «Орион Про» на нём — напишите мне, сделаю версию под него.")
        servers = collect_servers(e_srv.get().strip())
        log("Ищу сервер: перебираю ВСЕ SQL-серверы на этом компьютере")
        log("(обычный путь и внутренний канал — это может занять до минуты)...")
        log("Кандидаты: " + ", ".join(servers))
        # если выбран «Логин и пароль SQL» — запасом пробуем и Windows-пользователя
        auth_list = [creds()]
        if auth_list[0] != (None, None):
            auth_list.append((None, None))
        st["dbs"] = []
        for srv in servers:
            for au in auth_list:
                try:
                    conn = connect(srv, "master", au[0], au[1])
                except Exception as ex:
                    log(f"  {srv} — не подключился ({str(ex).strip()[:80]})")
                    continue
                how = "логин/пароль SQL" if au[0] else "Windows-пользователь"
                log(f"  {srv} — ПОДКЛЮЧИЛСЯ ({how}), смотрю базы...")
                try:
                    dbs = find_orion_dbs(conn)
                except Exception as ex:
                    log(f"  ошибка списка баз: {ex}")
                    conn.close()
                    continue
                conn.close()
                if not dbs:
                    log("  На этом сервере баз «Орион Про» нет — пробую дальше...")
                    continue
                # запоминаем рабочий сервер и рабочий способ входа
                st["server"], st["auth_ok"] = srv, au
                e_srv.delete(0, "end")
                e_srv.insert(0, srv)
                for name, people in dbs:
                    label = f"{name}  ({people} чел.)" if people >= 0 else name
                    st["dbs"].append((label, name))
                cb_db["values"] = [x[0] for x in st["dbs"]]
                cb_db.current(0)
                log(f"  НАЙДЕНО баз «Орион Про»: {len(dbs)} — выберите свою в списке «База данных».")
                if len(dbs) > 1:
                    log("  Если не знаете, какую выбрать — берите ту, где больше людей.")
                return
        log("Не нашёл. Нажмите «ДИАГНОСТИКА» и пришлите мне файл Диагностика_Болид.txt —")
        log("по нему скажу точно, что делать (или включим запасной план с копией .bak).")

    def current_db():
        v = cb_db.get()
        for label, name in st["dbs"]:
            if label == v:
                return name
        return v

    def do_run():
        srv = e_srv.get().strip() or st.get("server", "")
        db = current_db().strip()
        if not srv or not db:
            messagebox.showwarning(
                "Не всё заполнено",
                "Нажмите «НАЙТИ БАЗУ ОРИОНА» — программа сама найдёт сервер и базу\n"
                "(вводить название сервера не нужно).")
            return
        out = e_out.get().strip()
        os.makedirs(out, exist_ok=True)
        user, pwd = st.get("auth_ok") or creds()
        try:
            csv_path, stats = do_export(srv, db, user, pwd, out, log)
        except Exception as ex:
            log(f"ОШИБКА: {ex}")
            messagebox.showerror("Ошибка", f"{ex}\n\nНажмите «ДИАГНОСТИКА» и пришлите файл мне.")
            return
        log("=" * 50)
        log(f"ВЫГРУЗКА ГОТОВА: {csv_path}")
        log(f"  людей: {stats['people']}, ключей: {stats['codes']}, фото: {stats['photos']}")
        messagebox.showinfo(
            "Готово",
            f"Выгрузка готова:\n{csv_path}\n\n"
            f"Людей: {stats['people']}\nКлючей/карт: {stats['codes']}\nФотографий: {stats['photos']}\n\n"
            f"Теперь запустите «Миграция Болид → Sigur» и выберите файл Болид_выгрузка.csv")

    def do_diag_btn():
        p = os.path.join(e_out.get().strip() or ".", "Диагностика_Болид.txt")
        try:
            do_diag(e_srv.get().strip(), current_db().strip(), *creds(), p, log)
        except Exception as ex:
            log(f"Диагностика не удалась: {ex}")
            return
        messagebox.showinfo("Диагностика", f"Сохранено:\n{p}\n\nПришлите этот файл, если что-то не работает.")

    ttk.Button(btns, text="НАЙТИ БАЗУ ОРИОНА", command=do_find).pack(side="left")
    ttk.Button(btns, text="ВЫГРУЗИТЬ ВСЁ", command=do_run).pack(side="left", padx=10)
    ttk.Button(btns, text="ДИАГНОСТИКА", command=do_diag_btn).pack(side="right")

    box = ttk.LabelFrame(root, text="Сообщения", padding=6)
    box.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    txt_log = tk.Text(box, height=10, wrap="word", state="disabled")
    txt_log.pack(fill="both", expand=True)

    log(f"{APP} v{VER}")
    log("Программа читает базу «Орион Про» напрямую: люди, ВСЕ ключи/карты и ФОТОГРАФИИ.")
    log("В базе ничего не меняется — только чтение.")
    log("Сервер, имя базы, логин и пароль возьмите из окна «Ориона»:")
    log("Менеджер сервера → Сервис → Параметры БД, затем «НАЙТИ БАЗУ ОРИОНА».")
    disc = find_sql_instances()[0]
    for name, _val in registry_instances():
        disc.append("localhost" if name.upper() == "MSSQLSERVER"
                    else "localhost\\" + name)
    if disc:
        e_srv.insert(0, disc[0])
        log(f"Найден SQL на этом компьютере: {', '.join(disc)} — поле сервера можно не трогать.")
    else:
        log("Поле «Сервер MS SQL» можно оставить ПУСТЫМ — при нажатии «НАЙТИ БАЗУ")
        log("ОРИОНА» программа сама переберёт все варианты и найдёт рабочий.")
    root.mainloop()


if __name__ == "__main__":
    try:
        run_gui()
    except Exception:
        err = traceback.format_exc()
        try:
            open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ошибка_выгрузки.txt"),
                 "w", encoding="utf-8").write(err)
        except Exception:
            pass
        try:
            import tkinter as tk
            import tkinter.messagebox as mb
            tk.Tk().withdraw()
            mb.showerror("Ошибка", "Что-то пошло не так. Подробности — в файле ошибка_выгрузки.txt\n\n" + err[-900:])
        except Exception:
            print(err)
        sys.exit(1)
