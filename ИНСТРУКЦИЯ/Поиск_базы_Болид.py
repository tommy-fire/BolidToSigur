#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ПОИСК БАЗЫ ДАННЫХ «ОРИОН ПРО» НА ЭТОМ КОМПЬЮТЕРЕ

Диагностика: находит службы SQL, установленные экземпляры, перебирает все
драйверы и серверы, проверяет каждую базу на таблицы pList/pMark, ищет
файлы .mdf и настройки «Ориона». Ничего не меняет — только читает.

Результат сохраняет в файл «Поиск_базы_отчёт.txt» рядом с собой.
Пришлите этот файл — и станет ясно, где база и что вписать в программу.
"""
import os, sys, re, subprocess, platform

REPORT = []


def out(s=""):
    print(s)
    REPORT.append(s)


def section(t):
    out()
    out("=" * 66)
    out(t)
    out("=" * 66)


def ask(prompt):
    """Вопрос человеку (Enter = пропустить). От сбоев ввода защищены."""
    try:
        return input(prompt).strip()
    except Exception:
        return ""


# ------------------------------------------------------------ службы Windows
def read_services():
    """Список служб [{name, display, state}] через sc query."""
    try:
        raw = subprocess.run(["sc", "query", "type=", "service", "state=", "all"],
                             capture_output=True, timeout=120).stdout
        text = raw.decode("cp866", "ignore")
    except Exception as ex:
        return [], f"sc query не выполнился: {ex}"
    svc, cur = [], None
    for line in text.splitlines():
        ls = line.strip()
        low = ls.lower()
        if low.startswith("service_name:"):
            if cur:
                svc.append(cur)
            cur = {"name": ls.split(":", 1)[1].strip(), "display": "", "state": ""}
        elif cur is not None:
            if low.startswith("display_name:"):
                cur["display"] = ls.split(":", 1)[1].strip()
            elif low.startswith("state"):
                cur["state"] = ls.split(":", 1)[1].strip()
    if cur:
        svc.append(cur)
    return svc, ""


# ------------------------------------------------------------ драйверы
def sql_drivers():
    try:
        import pyodbc
        ds = list(pyodbc.drivers())
    except Exception as ex:
        out(f"  pyodbc недоступен ({ex}) — сначала запустите")
        out("  Запустить_выгрузку_из_Болид.bat один раз, чтобы он установился.")
        return []
    prio = ["SQL Server", "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server", "ODBC Driver 13 for SQL Server",
            "SQL Server Native Client 11.0", "SQL Server Native Client 10.0"]
    found = [d for d in prio if d in ds]
    found += [d for d in ds if d not in found and "SQL" in d.upper()]
    return found


def cs_for(drv, server, db, user=None, pwd=None):
    cs = f"DRIVER={{{drv}}};SERVER={server};DATABASE={db};"
    if user:
        cs += f"UID={user};PWD={pwd};"
    else:
        cs += "Trusted_Connection=yes;"
    if "ODBC Driver 1" in drv:
        cs += "Encrypt=no;TrustServerCertificate=yes;"
    return cs


# ------------------------------------------------------------ экземпляры из реестра
def registry_instances():
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


# ------------------------------------------------------------ поиск на диске
def find_files(roots, exts, limit=60):
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            if dirpath.count(os.sep) - root.count(os.sep) > 7:
                dirs[:] = []
            for f in files:
                if f.lower().endswith(exts):
                    found.append(os.path.join(dirpath, f))
                    if len(found) >= limit:
                        return found
    return found


def bolid_ini_lines():
    """Ищем настройки «Ориона» в ini-файлах (пароли маскируются)."""
    inis = find_files([r"C:\BOLID", r"C:\Program Files (x86)\Bolid",
                       r"C:\Program Files\Bolid", r"C:\ORIONBASE"],
                      (".ini",), limit=30)
    hits = []
    kw = re.compile(r"server|data ?source|database|база|каталог|dir=|provider|uid",
                    re.IGNORECASE)
    for ini in inis:
        try:
            lines = open(ini, encoding="cp1251", errors="ignore").read().splitlines()
        except Exception:
            continue
        for ln in lines:
            if kw.search(ln) and len(ln) < 200:
                s = re.sub(r"(?i)(pwd|password|пароль)\s*=.*", r"\1=***", ln.strip())
                hits.append(f"{os.path.basename(ini)}: {s}")
    return inis, hits[:40]


# ============================================================ ГЛАВНЫЙ ХОД
def main():
    section("ПОИСК БАЗЫ «ОРИОН ПРО» — ДИАГНОСТИКА")
    out(f"Компьютер : {platform.node()}")
    out(f"Система   : {platform.platform()}")

    # --- 0. параметры из окна «Параметры БД», если человек их знает
    print()
    print("Если открыто окно «Орион Про» → Менеджер сервера → Сервис → Параметры БД,")
    print("введите его значения — поиск получится точнее (база только читается):")
    srv_in = ask("Имя сервера SQL (Enter — пропустить): ")
    user_in = ask("Логин SQL (Enter — пропустить): ")
    pwd_in = ask("Пароль SQL (Enter — пропустить): ")
    out(f"Указано: сервер = {srv_in or '—'}, логин SQL = {user_in or '—'} "
        "(пароль в отчёт не пишется)")

    # --- 1. службы
    section("1. СЛУЖБЫ БАЗ ДАННЫХ И «ОРИОНА»")
    svc, err = read_services()
    if err:
        out(f"  {err}")
    interesting = [s for s in svc if re.search(
        r"mssql|sql|postgres|orion|bolid|firebird", (s["name"] + " " + s["display"]), re.I)]
    if not interesting:
        out("  Ничего SQL-подобного не найдено. Возможно, база на ДРУГОМ компьютере")
        out("  (запускать программу надо там, где стоит сервер «Орион Про»),")
        out("  либо это старая версия «Орион» (не Про) без SQL-базы.")
    servers = []
    for s in interesting:
        out(f"  {s['name']}  [{s['state']}]  — {s['display']}")
        l = s["name"].lower()
        if l.startswith("mssql$"):
            servers.append("localhost\\" + s["name"].split("$", 1)[1])
        elif l == "mssqlserver":
            servers.append("localhost")

    # --- 2. экземпляры из реестра
    section("2. ЭКЗЕМПЛЯРЫ MS SQL В РЕЕСТРЕ")
    reg = registry_instances()
    if reg:
        for name, val in reg:
            out(f"  экземпляр «{name}»  ({val})")
            if name.upper() != "MSSQLSERVER":
                servers.append(f"localhost\\{name}")
            else:
                servers.append("localhost")
    else:
        out("  В реестре экземпляров MS SQL не найдено.")

    # --- 3. драйверы
    section("3. УСТАНОВЛЕННЫЕ ДРАЙВЕРЫ ODBC")
    drivers = sql_drivers()
    if drivers:
        for d in drivers:
            out(f"  {d}")
        if not any(d == "SQL Server" for d in drivers):
            out("  ВНИМАНИЕ: старого драйвера «SQL Server» нет (удалён из новых Windows).")
            out("  Основную программу выгрузки скачайте заново — она уже умеет")
            out("  работать с новыми драйверами.")
    else:
        out("  Драйверы определить не удалось.")

    # --- 4. перебор серверов
    auth_txt = f"сначала логин SQL «{user_in}», затем Windows" if user_in \
        else "Windows-аутентификация"
    section(f"4. ПОПЫТКИ ПОДКЛЮЧЕНИЯ ({auth_txt}; обычный адрес и внутренний lpc:)")
    node = platform.node()
    extra = [node, node + "\\SQLEXPRESS"] if node else []
    seen, uniq = [], set()
    for s in ([srv_in] if srv_in else []) + servers + \
             ["localhost\\SQLEXPRESS", "localhost"] + extra:
        if s not in uniq:
            uniq.add(s)
            seen.append(s)
    conn = None
    if drivers:
        import pyodbc
        modes = []
        if user_in:
            modes.append((f"SQL-логин «{user_in}»", user_in, pwd_in))
        modes.append(("Windows-пользователь", None, None))
        for srv in seen:
            variants = [srv]
            if not re.match(r"^(lpc|np|tcp):", srv, re.I):
                variants.append("lpc:" + srv)
            for variant in variants:
                for mname, mu, mp in modes:
                    for drv in drivers:
                        try:
                            conn = pyodbc.connect(cs_for(drv, variant, "master", mu, mp),
                                                  timeout=6)
                            out(f"  ПОДКЛЮЧЕНО: {variant}  (драйвер «{drv}», {mname})")
                            break
                        except Exception as ex:
                            out(f"  {variant} / {drv} / {mname}: "
                                f"{str(ex).strip().splitlines()[0][:100]}")
                    if conn:
                        break
                if conn:
                    break
            if conn:
                break
    else:
        out("  Драйверы недоступны — подключения не пробовались (см. раздел 3).")
    if not conn:
        out("  Подключиться не удалось. Частые причины:")
        if not user_in:
            out("  • базе нужен логин/пароль SQL — перезапустите программу и введите их")
            out("    (видны в «Менеджер сервера» → Сервис → Параметры БД)")
        out("  • служба SQL остановлена (см. раздел 1 — состояние)")
        out("  • это PostgreSQL, а не MS SQL")
        out("  • база на другом компьютере")

    # --- 5. если подключились — ищем pList/pMark
    found_dbs = []
    if conn:
        section("5. ПРОВЕРКА БАЗ НА ТАБЛИЦЫ pList / pMark")
        cur = conn.cursor()
        try:
            dbs = [r[0] for r in cur.execute(
                "SELECT name FROM sys.databases WHERE database_id NOT IN (1,2,3,4)").fetchall()]
        except Exception as ex:
            dbs, out_dbs = [], f"  не удалось получить список баз: {ex}"
        out(f"  Базы на сервере: {', '.join(dbs) or '—'}")
        for db in dbs:
            try:
                n_pl = cur.execute(f"SELECT COUNT(*) FROM [{db}].INFORMATION_SCHEMA.TABLES "
                                   "WHERE TABLE_NAME = 'pList'").fetchone()[0]
                n_mk = cur.execute(f"SELECT COUNT(*) FROM [{db}].INFORMATION_SCHEMA.TABLES "
                                   "WHERE TABLE_NAME = 'pMark'").fetchone()[0]
                if n_pl or n_mk:
                    people = "?"
                    try:
                        people = cur.execute(f"SELECT COUNT(*) FROM [{db}].dbo.pList").fetchone()[0]
                    except Exception:
                        pass
                    out(f"  >>> НАЙДЕНА БАЗА «{db}»: pList={'да' if n_pl else 'НЕТ'}, "
                        f"pMark={'да' if n_mk else 'НЕТ'}, людей: {people}")
                    if n_pl and n_mk:
                        found_dbs.append(db)
            except Exception as ex:
                out(f"  база {db}: {str(ex)[:60]}")
        if not found_dbs:
            out("  Полного набора pList+pMark нет. Таблицы всех баз (для проверки):")
            for db in dbs:
                try:
                    ts = [r[0] for r in cur.execute(
                        f"SELECT TOP 25 TABLE_NAME FROM [{db}].INFORMATION_SCHEMA.TABLES "
                        "WHERE TABLE_TYPE='BASE TABLE'").fetchall()]
                    if ts:
                        out(f"  {db}: {', '.join(ts)}")
                except Exception:
                    pass
        section("6. ФАЙЛЫ БАЗ (.mdf)")
        try:
            for name, fn in cur.execute(
                    "SELECT DB_NAME(database_id), physical_name FROM sys.master_files "
                    "WHERE physical_name LIKE '%.mdf'").fetchall():
                out(f"  {name}: {fn}")
        except Exception:
            pass
        conn.close()

    # --- 7. диск и ini (если базы не нашли или не подключились)
    if not found_dbs:
        section("7. ПОИСК ФАЙЛОВ БАЗ И НАСТРОЕК НА ДИСКЕ")
        roots = [r"C:\ORIONBASE", r"C:\BOLID",
                 r"C:\Program Files\Microsoft SQL Server",
                 r"C:\Program Files (x86)\Microsoft SQL Server"]
        if os.path.isdir("D:\\"):
            roots += ["D:\\ORIONBASE", "D:\\BOLID"]
        mdfs = find_files(roots, (".mdf",))
        out("  Файлы .mdf (сами базы):")
        for f in mdfs[:30] or []:
            out(f"    {f}")
        if not mdfs:
            out("    не найдены в типовых папках")
        inis, hits = bolid_ini_lines()
        out("  Настройки «Ориона» из ini-файлов (пароли скрыты):")
        for h in hits or []:
            out(f"    {h}")
        if not hits:
            out("    не найдены")

    # --- итог
    section("ИТОГ")
    if found_dbs:
        out(f"  База «Орион Про» найдена: {', '.join(found_dbs)}")
        out("  Что делать: откройте программу выгрузки (Выгрузка_из_Болид), впишите")
        out("  сервер из раздела 4, включите «Логин и пароль SQL» (значения — из")
        out("  «Параметров БД» Ориона), нажмите «НАЙТИ БАЗУ ОРИОНА» и выберите базу.")
    else:
        out("  Базу автоматически найти не удалось.")
        out("  ПРИШЛИТЕ ФАЙЛ «Поиск_базы_отчёт.txt» (лежит рядом с программой) —")
        out("  по нему я скажу точно, что делать дальше.")
    out()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        out("ОШИБКА ВЫПОЛНЕНИЯ:")
        out(traceback.format_exc())
    rep = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Поиск_базы_отчёт.txt")
    open(rep, "w", encoding="utf-8").write("\n".join(REPORT))
    print()
    print("=" * 66)
    print(f"Отчёт сохранён: {rep}")
    print("Пришлите этот файл, если база не нашлась.")
    try:
        input("Нажмите Enter, чтобы закрыть окно...")
    except Exception:
        pass
