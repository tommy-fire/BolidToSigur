#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ВЫГРУЗКА ИЗ РЕЗЕРВНОЙ КОПИИ БАЗЫ «ОРИОН ПРО» (ФАЙЛ .BAK) — ЗАПАСНОЙ ПУТЬ

Если прямое чтение рабочей базы не выходит, используем резервную копию:
  1. Вы делаете резервную копию базы в «Менеджер сервера» «Ориона» (.bak).
  2. Эта программа разворачивает копию в ОТДЕЛЬНУЮ временную базу
     (имя OrionCopyExport) — рабочая база не трогается вообще.
  3. Выгружает из копии то же самое: люди, ВСЕ ключи/карты, фотографии.
  4. Временную базу удаляет.

Результат — те же файлы, что и у основной программы выгрузки:
    Болид_выгрузка.csv   — люди, все их данные и ВСЕ коды карт
    Фотографии\          — фотографии сотрудников
    Отчёт_выгрузки.txt   — что и сколько выгрузилось
"""
import os, re, sys, csv, traceback, queue, threading

APP = "Выгрузка из резервной копии «Орион Про»"
VER = "v.01"
COPY_DB = "OrionCopyExport"
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "Лог_выгрузки_из_копии.txt")


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


def pick(cols, names):
    low = {k.lower(): k for k in cols}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


def first_line(ex, n=170):
    """Первая строка текста ошибки (для коротких сообщений человеку)."""
    s = str(ex).strip()
    return s.splitlines()[0][:n] if s else repr(ex)


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
        raise RuntimeError("Не нашёл колонку фамилии в pList — пришлите лог программы.")
    if not codep:
        raise RuntimeError("Не нашёл колонку кодов (CodeP) в pMark — пришлите лог программы.")
    if not owner:
        raise RuntimeError("Не нашёл колонку связи (Owner) в pMark — пришлите лог программы.")

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
        f.write("ОТЧЁТ ВЫГРУЗКИ ИЗ РЕЗЕРВНОЙ КОПИИ «ОРИОН ПРО»\n" + "=" * 62 + "\n\n")
        f.write(f"Файл копии .......... (см. лог программы)\n")
        f.write(f"Временная база ...... {db}\n")
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


# ============================================================ восстановление копии
def sql_str(s):
    """Строка для безопасной подстановки в SQL-команду."""
    return str(s).replace("'", "''")


def restore_copy(conn, bak_path, log):
    """Разворачивает .bak в отдельную временную базу COPY_DB.

    Рабочая база не трогается: у копии своё имя и свои файлы.
    Возвращает (True, сообщение) или (False, что случилось)."""
    cur = conn.cursor()
    log("Читаю состав резервной копии...")
    try:
        rows = cur.execute(
            f"RESTORE FILELISTONLY FROM DISK = '{sql_str(bak_path)}'").fetchall()
    except Exception as ex:
        return False, ("Не удалось прочитать файл копии: " + first_line(ex) +
                       "\n\nПроверь, что выбран файл .bak из «Менеджер сервера» Ориона.")
    data_files = [r for r in rows if str(r[2]).strip().upper() == "D"]
    log_files = [r for r in rows if str(r[2]).strip().upper() == "L"]
    if not data_files:
        return False, "В копии не нашлось файлов данных — пришли мне файл лога программы."

    # файлы временной базы кладём в ту же папку, где лежит рабочая база
    base_dir = os.path.dirname(str(data_files[0][1])) or "C:\\"
    moves = []
    for i, r in enumerate(data_files):
        fn = os.path.join(base_dir,
                          COPY_DB + (".mdf" if len(data_files) == 1 else f"_{i}.mdf"))
        moves.append(f"MOVE N'{sql_str(r[0])}' TO N'{sql_str(fn)}'")
    for i, r in enumerate(log_files):
        fn = os.path.join(base_dir,
                          COPY_DB + "_log" + (".ldf" if len(log_files) == 1 else f"_{i}.ldf"))
        moves.append(f"MOVE N'{sql_str(r[0])}' TO N'{sql_str(fn)}'")

    # убрать нашу временную базу, если осталась с прошлого раза
    # (удаляется ТОЛЬКО база с нашим именем COPY_DB — рабочая база не трогается)
    try:
        cur.execute(f"IF DB_ID('{COPY_DB}') IS NOT NULL DROP DATABASE [{COPY_DB}]")
    except Exception:
        pass

    log(f"Разворачиваю копию в отдельную базу «{COPY_DB}» — рабочая база не трогается.")
    log("Это может занять несколько минут. Не закрывай программу.")
    try:
        cur.execute(f"RESTORE DATABASE [{COPY_DB}] FROM DISK = '{sql_str(bak_path)}' "
                    "WITH REPLACE, " + ", ".join(moves))
    except Exception as ex:
        return False, ("Восстановление копии не удалось: " + first_line(ex, 200) +
                       "\n\nЧастые причины: не хватает места на диске (нужно примерно"
                       " столько же, сколько весит файл копии), либо у логина нет прав."
                       " Пришли мне файл Лог_выгрузки_из_копии.txt")
    return True, "Копия развёрнута."


def drop_copy(server, user, pwd, log):
    """Удаляет временную базу-копию (только с именем COPY_DB)."""
    try:
        conn = connect(server, "master", user, pwd)
        conn.cursor().execute(f"IF DB_ID('{COPY_DB}') IS NOT NULL DROP DATABASE [{COPY_DB}]")
        conn.close()
        log(f"Временная база «{COPY_DB}» удалена (это была копия, не рабочая база).")
    except Exception as ex:
        log("Временную базу удалить не удалось (" + first_line(ex, 100) +
            ") — на выгрузку это не влияет; она удалится при следующем запуске.")


# ============================================================ GUI
def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title(f"{APP}  v{VER}")
    root.geometry("1000x720")

    q = queue.Queue()
    logs = []
    state = {"done": True}

    def append_log(s):
        txt_log.configure(state="normal")
        txt_log.insert("end", s + "\n")
        txt_log.see("end")
        txt_log.configure(state="disabled")
        logs.append(s)

    def poll():
        try:
            while True:
                item = q.get_nowait()
                if item[0] == "log":
                    append_log(item[1])
                elif item[0] == "done":
                    ok, msg = item[1], item[2]
                    if not state["done"]:
                        state["done"] = True
                        btn_run.configure(state="normal")
                        try:
                            open(LOG_PATH, "w", encoding="utf-8").write("\n".join(logs))
                        except Exception:
                            pass
                        if ok:
                            messagebox.showinfo("Готово", msg)
                        else:
                            messagebox.showerror(
                                "Не получилось",
                                msg + "\n\nПодробности — в файле Лог_выгрузки_из_копии.txt"
                                      " (лежит рядом с программой). Пришли его мне.")
        except queue.Empty:
            pass
        root.after(200, poll)

    def log(s):
        q.put(("log", s))

    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")

    ttk.Label(top, text="Файл копии (.bak):").grid(row=0, column=0, sticky="w")
    e_bak = ttk.Entry(top, width=46)
    e_bak.grid(row=0, column=1, padx=6, sticky="ew")
    ttk.Button(top, text="Обзор…", command=lambda: pick_bak()).grid(row=0, column=2)

    ttk.Label(top, text="Сервер MS SQL (необязательно):").grid(row=1, column=0, sticky="w", pady=(8, 0))
    e_srv = ttk.Entry(top, width=46)
    e_srv.grid(row=1, column=1, padx=6, pady=(8, 0), sticky="ew")

    auth = tk.StringVar(value="win")
    af = ttk.LabelFrame(top, text="Как подключаться к базе", padding=6)
    af.grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
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
    e_out = ttk.Entry(top, width=46)
    e_out.grid(row=3, column=1, padx=6, pady=(10, 0), sticky="ew")
    e_out.insert(0, os.path.dirname(os.path.abspath(__file__)))
    ttk.Button(top, text="Обзор…", command=lambda: pick_out()).grid(row=3, column=2, pady=(10, 0))
    top.columnconfigure(1, weight=1)

    var_drop = tk.BooleanVar(value=True)
    ttk.Checkbutton(top, variable=var_drop,
                    text="Удалить временную базу-копию после выгрузки (рабочая база «Ориона» "
                         "не затрагивается никогда)").grid(row=4, column=0, columnspan=3,
                                                           sticky="w", pady=(8, 0))

    btns = ttk.Frame(root, padding=8)
    btns.pack(fill="x")

    def pick_bak():
        p = filedialog.askopenfilename(
            title="Выбери файл резервной копии базы",
            filetypes=[("Резервная копия", "*.bak"), ("Все файлы", "*.*")])
        if p:
            e_bak.delete(0, "end")
            e_bak.insert(0, p)

    def pick_out():
        p = filedialog.askdirectory(title="Куда сохранить выгрузку")
        if p:
            e_out.delete(0, "end")
            e_out.insert(0, p)

    def creds():
        return (e_user.get().strip(), e_pwd.get()) if auth.get() == "sql" else (None, None)

    def worker(bak, srv, user, pwd, out, do_drop):
        try:
            cands = collect_servers(srv)
            if srv:
                log(f"Подключаюсь к серверу {srv} (не выйдет — переберу все остальные)...")
            else:
                log("Подключаюсь: перебираю все SQL-серверы на этом компьютере...")
            conn, srv_ok = None, ""
            for s in cands:
                try:
                    conn = connect(s, "master", user, pwd)
                    srv_ok = s
                    break
                except Exception as ex:
                    log(f"  {s} — не подключился ({first_line(ex, 80)})")
            if not conn:
                q.put(("done", False,
                       "Не удалось подключиться ни к одному SQL-серверу на этом компьютере.\n"
                       "Запусти основную программу выгрузки, нажми «ДИАГНОСТИКА»\n"
                       "и пришли мне файл Диагностика_Болид.txt"))
                return
            log(f"Подключение удалось ({srv_ok}).")
            ok, msg = restore_copy(conn, bak, log)
            conn.close()
            if not ok:
                q.put(("done", False, msg))
                return
            log("Выгружаю людей, ключи и фотографии из копии...")
            csv_path, stats = do_export(srv_ok, COPY_DB, user, pwd, out, log)
            if do_drop:
                drop_copy(srv_ok, user, pwd, log)
            log("=" * 50)
            log(f"ВЫГРУЗКА ГОТОВА: {csv_path}")
            log(f"  людей: {stats['people']}, ключей: {stats['codes']}, фото: {stats['photos']}")
            q.put(("done", True,
                   f"Выгрузка готова:\n{csv_path}\n\n"
                   f"Людей: {stats['people']}\nКлючей/карт: {stats['codes']}\n"
                   f"Фотографий: {stats['photos']}\n\n"
                   "Дальше как обычно: запусти «Миграция Болид → Sigur» и выбери "
                   "файл Болид_выгрузка.csv"))
        except Exception as ex:
            log(f"ОШИБКА: {ex}")
            q.put(("done", False, first_line(ex, 300)))

    def do_run():
        bak = e_bak.get().strip()
        srv = e_srv.get().strip()
        out = e_out.get().strip()
        if not bak:
            messagebox.showwarning(
                "Не всё заполнено",
                "Укажи файл копии (.bak) — кнопка «Обзор…».\n\n"
                "Сервер вводить НЕ обязательно: программа сама переберёт все варианты.\n"
                "Логин и пароль — из окна Ориона (User name / Password),\n"
                "если знаешь их.")
            return
        if not os.path.isfile(bak):
            messagebox.showwarning("Файл не найден", f"По этому адресу файла нет:\n{bak}")
            return
        os.makedirs(out, exist_ok=True)
        user, pwd = creds()
        size_mb = os.path.getsize(bak) // (1024 * 1024)
        log("=" * 50)
        log(f"Начинаю. Файл копии: {bak} ({size_mb} МБ)")
        if size_mb < 1:
            log("ВНИМАНИЕ: файл подозрительно маленький для копии базы — но пробую.")
        btn_run.configure(state="disabled")
        state["done"] = False
        threading.Thread(target=worker,
                         args=(bak, srv, user, pwd, out, var_drop.get()),
                         daemon=True).start()

    btn_run = ttk.Button(btns, text="ВОССТАНОВИТЬ КОПИЮ И ВЫГРУЗИТЬ ВСЁ", command=do_run)
    btn_run.pack(side="left")

    box = ttk.LabelFrame(root, text="Сообщения", padding=6)
    box.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    txt_log = tk.Text(box, height=10, wrap="word", state="disabled")
    txt_log.pack(fill="both", expand=True)

    log(f"{APP} v{VER} — запасной путь через резервную копию")
    log("Программа развернёт копию во ВРЕМЕННУЮ базу с другим именем и выгрузит")
    log("из неё данные. Рабочая база «Ориона» не затрагивается вообще.")
    if find_sql_instances()[1]:
        log("ОБНАРУЖЕН PostgreSQL — эта программа только для MS SQL. Напиши мне.")
    disc = find_sql_instances()[0]
    for name, _val in registry_instances():
        disc.append("localhost" if name.upper() == "MSSQLSERVER"
                    else "localhost\\" + name)
    if disc:
        e_srv.insert(0, disc[0])
        log(f"Найден SQL на этом компьютере: {', '.join(disc)} — поле сервера можно не трогать.")
    else:
        log("Поле «Сервер MS SQL» можно оставить ПУСТЫМ — программа сама найдёт сервер.")
    log("Порядок: выбери файл .bak → (сервер не нужен) → логин/пароль, если знаешь → кнопка.")
    root.after(200, poll)
    root.mainloop()


if __name__ == "__main__":
    try:
        run_gui()
    except Exception:
        err = traceback.format_exc()
        try:
            open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "ошибка_копии.txt"), "w", encoding="utf-8").write(err)
        except Exception:
            pass
        try:
            import tkinter as tk
            import tkinter.messagebox as mb
            tk.Tk().withdraw()
            mb.showerror("Ошибка", "Что-то пошло не так. Подробности — в файле "
                         "ошибка_копии.txt\n\n" + err[-900:])
        except Exception:
            print(err)
        sys.exit(1)
