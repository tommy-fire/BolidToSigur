#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Established SQL discovery/connection helpers, used only on the first tab.
The GUI calls safe_w34.snapshot and transfer_bundle.pack to save a .bolid file.
No writes to the Bolid database. ODBC is not needed to open a saved .bolid file.
"""
import os, re, sys, csv, traceback

APP = "Полная выгрузка из базы «Орион Про»"
VER = "v.03"

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
                cs += "UID={" + str(user).replace("}", "}}") + "};PWD={" + str(pwd or "").replace("}", "}}") + "};"
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


