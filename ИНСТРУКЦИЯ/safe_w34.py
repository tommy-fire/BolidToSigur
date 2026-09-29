"""Strict, offline-verifiable W34 migration. No writes to source or destination DB.
Community CodeP layout is a supported hypothesis, not a universal Bolid format.
"""
import csv, json, re, os, datetime, importlib.machinery, importlib.util
from pathlib import Path

# Photos in HEX may exceed the default CSV parser field limit.
csv.field_size_limit(2**31-1)

HEX = re.compile(r'[0-9A-Fa-f]+')

def unhex(s):
    s = str(s).strip()
    if s.lower().startswith('0x'): s = s[2:]
    s = s.replace(' ', '')
    if not s or len(s) % 2 or not HEX.fullmatch(s):
        raise ValueError('Нужен HEX чётной длины без потери нулей')
    return bytes.fromhex(s)

def crc8(data):
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8): crc = (crc >> 1) ^ (0x8C if crc & 1 else 0)
    return crc

def decode(raw, mode='raw'):
    b = unhex(raw)
    if mode == 'raw':
        if b[0] != 8: raise ValueError('Неизвестный префикс CodeP (ожидался 08)')
        out = bytearray(); i = 1
        while i < len(b):
            v = b[i]; i += 1
            if v == 0: raise ValueError('Неэкранированный 00: другой формат источника')
            if v == 254:
                if i == len(b) or b[i] not in (1, 2):
                    raise ValueError('Неизвестная/оборванная FE-последовательность')
                v = {1:0, 2:254}[b[i]]; i += 1
            out.append(v)
        b = bytes(out)
    elif mode == 'abd': b = b[::-1]
    else: raise ValueError('Формат должен быть raw или abd')
    if len(b) != 8: raise ValueError('После разбора должно быть ровно 8 байт')
    if b[0] != 1: raise ValueError('Неизвестное семейство ключа (не 01)')
    if crc8(b[:7]) != b[7]: raise ValueError('Не совпала CRC8/MAXIM')
    abd = b[::-1].hex().upper()
    return abd, abd[-10:-2]

def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f, delimiter=';'))

def write_csv(path, rows, fields):
    path = Path(path); tmp = path.with_suffix(path.suffix+'.tmp')
    with open(tmp, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fields, delimiter=';', extrasaction='ignore')
        w.writeheader(); w.writerows(rows)
    os.replace(tmp, path)

def load_exporter():
    import bolid_db
    return bolid_db


def discover(user='', password='', manual='', log=lambda _: None):
    """Reuse established discovery, record the actual successful auth per result."""
    e = load_exporter()
    servers = e.collect_servers(manual)
    result = []
    for server in servers:
        auths = [(user or None, password)]
        if user: auths.append((None, None))
        for u, pw in auths:
            log(f'Проверяю {server} ({"SQL" if u else "Windows"})...')
            try: conn = e.connect(server, 'master', u, pw)
            except Exception:
                log(f'{server}: подключиться этим способом не удалось')
                continue
            try:
                dbs = e.find_orion_dbs(conn)
            except Exception:
                log(f'{server}: не удалось прочитать список баз')
                dbs = []
            finally: conn.close()
            for db, n in dbs:
                result.append({'server': server, 'db': db, 'people': n,
                               'user': u, 'password': pw})
            if dbs:
                log(f'Найдено баз: {len(dbs)}. Выберите рабочую, не по числу сотрудников.')
                return result
    return result


def snapshot(server, db, user, password, out):
    """Export each table independently, retaining orphan marks and binary fields."""
    e = load_exporter(); root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    dest = root / ('snapshot_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    dest.mkdir()
    conn = e.connect(server, db, user or None, password)
    meta = {'version':'safe-w34-3', 'warnings':[], 'tables':{}, 'consistency':'separate SELECT statements, not a transactional snapshot'}
    try:
        cur = conn.cursor()
        for table in ('pList', 'pMark', 'PCompany', 'PDivision', 'PPost', 'Company', 'Firm', 'Section', 'pSection', 'Department', 'Post', 'Posts', 'Position'):
            matches = cur.execute('SELECT TABLE_SCHEMA,TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME=? AND TABLE_TYPE=\'BASE TABLE\'',table).fetchall()
            if len(matches) != 1:
                if table in ('pList','pMark'):
                    raise ValueError(f'{table}: найдено таблиц {len(matches)}, нужна однозначная схема')
                if matches: meta['warnings'].append(f'{table}: несколько схем, справочник пропущен')
                continue
            schema, actual = matches[0]
            cols = cur.execute('SELECT COLUMN_NAME,DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=? AND TABLE_NAME=? ORDER BY ORDINAL_POSITION',schema,actual).fetchall()
            fields = [r[0] for r in cols]
            selects = []
            for name, typ in cols:
                q = e.qi(name)
                # Serialize varchar CodeP on server: don't round-trip through Unicode.
                if typ in ('binary','varbinary','image','timestamp','rowversion') or (name.lower() in ('codep','codepadd') and typ in ('varchar','char','text')):
                    q = f'CONVERT(varbinary(max), {q})'
                selects.append(q)
            rows = cur.execute('SELECT '+','.join(selects)+' FROM '+e.qi(schema)+'.'+e.qi(actual))
            n = 0
            with open(dest/(table+'.csv'), 'w', encoding='utf-8-sig', newline='') as f:
                w = csv.writer(f, delimiter=';'); w.writerow(fields)
                for row in rows:
                    vals = []
                    for v in row:
                        if isinstance(v, (bytes, bytearray)): v = bytes(v).hex().upper()
                        elif isinstance(v, (datetime.datetime, datetime.date, datetime.time)): v = v.isoformat()
                        elif v is None: v = ''
                        vals.append(v)
                    w.writerow(vals); n += 1
            meta['tables'][table] = {'schema':schema,'columns':dict(cols),'rows':n}
        (dest/'schema.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
        (dest/'COMPLETE.txt').write_text('Оба SELECT завершены. NULL в CSV представлен пустой ячейкой. Фото/двоичные поля сохранены HEX. Не является резервной копией SQL.\n',encoding='utf-8')
    finally: conn.close()
    # Raw export is already complete even if enrichment encounters unsupported fields.
    from migration_data import enrich
    enrich(dest)
    return dest

def value(row, *names):
    low = {k.lower():v for k,v in row.items()}
    return next((low[n.lower()] for n in names if n.lower() in low), '')

REVIEW = ['SourceKeyID','SourcePersonID','ФИО','Табельный номер','Отдел','Должность','RawCodeP','Format','ABD','CandidateW34','DecodeError','Profile','ObservedW34','Approve','Срок действия','SourceMetadata','Исходный срок','Поле срока']

def prepare(folder):
    folder = Path(folder)
    if not (folder/'COMPLETE.txt').exists(): raise ValueError('Нет COMPLETE.txt: выгрузка не завершена')
    meta = json.loads((folder/'schema.json').read_text(encoding='utf-8'))
    marks = read_csv(folder/'pMark.csv'); persons = read_csv(folder/'pList.csv')
    lookup = {}
    for p in persons:
        pid = value(p,'ID')
        if not pid or pid in lookup: raise ValueError('pList.ID отсутствует или не уникален')
        lookup[pid] = p
    cp_type = next((t for n,t in meta['tables']['pMark']['columns'].items() if n.lower() == 'codep'),None)
    supported = cp_type in ('varchar','char','text','binary','varbinary','image')
    from migration_data import enrich, expiry_candidate
    details = enrich(folder)
    result = []; ids = set()
    for m in marks:
        kid = value(m,'ID'); pid = value(m,'Owner','OwnerID','Person')
        if not kid or kid in ids: raise ValueError('pMark.ID отсутствует или не уникален')
        ids.add(kid); p = lookup.get(pid,{})
        raw = value(m,'CodeP'); abd = candidate = error = ''
        try:
            if not supported: raise ValueError(f'Неподдерживаемый SQL-тип CodeP: {cp_type}')
            abd,candidate = decode(raw)
        except ValueError as ex: error = str(ex)
        if not p: error = 'Нет владельца pList; '+error
        result.append(dict(zip(REVIEW[:16],[kid,pid,' '.join(filter(None,[value(p,'Name','Surname','Family'),value(p,'FirstName'),value(p,'MidName','MiddleName')])),value(p,'TabNumber','Tab','Tabel'),'','',raw,'raw',abd,candidate,error,'','','','',json.dumps(m,ensure_ascii=False)])))
        person = details.get(pid,{})
        result[-1]['Отдел'] = person.get('dept','')
        result[-1]['Должность'] = person.get('post','')
        end_field, end_value = expiry_candidate(m)
        result[-1]['Исходный срок'] = end_value
        result[-1]['Поле срока'] = end_field
        # Preserved as metadata; user chooses whether this is really the expiry.
    target = folder/'Проверка.csv'
    if target.exists(): raise ValueError('Проверка.csv уже существует: не перезаписываю вашу проверку')
    write_csv(target,result,REVIEW)
    return target

def build(review_path, expiry_column=''):
    """Explicit approval required; no source status is interpreted as permission."""
    review_path = Path(review_path); rows = read_csv(review_path)
    profiles = {}; prepared = []; ids = set()
    for r in rows:
        kid = r.get('SourceKeyID','').strip()
        if not kid or kid in ids: raise ValueError('Пустой/повторный SourceKeyID')
        ids.add(kid)
        # Identity must correspond to the unmodified source export.
        r['_candidate'] = ''; r['_error'] = ''; r['_upper'] = ''
        try:
            abd,r['_candidate'] = decode(r.get('RawCodeP',''),r.get('Format','raw'))
            r['_upper'] = abd[2:6]
        except ValueError as ex: r['_error'] = str(ex)
        obs = r.get('ObservedW34','').strip().upper()
        if obs and not re.fullmatch('[0-9A-F]{8}',obs): raise ValueError(f'{kid}: ObservedW34 должен содержать 8 HEX-знаков')
        r['_observed'] = obs
        profile = r.get('Profile','').strip()
        if profile and obs:
            profiles.setdefault(profile,[]).append(r)
        prepared.append(r)
    calibrated = set(); profile_errors = {}; calibrated_upper = {}
    for profile, sample in profiles.items():
        if any(not r['_candidate'] or r['_candidate'] != r['_observed'] for r in sample):
            profile_errors[profile] = 'Есть несовпадение эталона; автоперенос профиля запрещён'
        elif all(bytes.fromhex(r['_observed'])[::-1].hex().upper() == r['_observed'] for r in sample):
            profile_errors[profile] = 'Контрольные номера симметричны по байтам: добавьте номер, отличающий порядок байтов'
        elif len({r['_observed'] for r in sample}) >= 3:
            calibrated.add(profile)
            calibrated_upper[profile] = {r['_upper'] for r in sample}
        else: profile_errors[profile] = 'Нужно минимум 3 различных номера, считанных в Sigur'
    source = review_path.parent
    if not (source/'COMPLETE.txt').exists(): raise ValueError('Проверка.csv должна лежать рядом с исходными pList.csv/pMark.csv')
    source_people = {value(p,'ID'):p for p in read_csv(source/'pList.csv')}
    source_marks = {value(m,'ID'):m for m in read_csv(source/'pMark.csv')}
    if ids != set(source_marks): raise ValueError('Состав SourceKeyID изменён относительно исходного pMark.csv')
    for r in prepared:
        original = source_marks[r['SourceKeyID']]
        if r.get('SourcePersonID','') != value(original,'Owner','OwnerID','Person') or r.get('RawCodeP','') != value(original,'CodeP') or r.get('Format','raw') != 'raw':
            raise ValueError('Изменены исходные код/владелец/формат: '+r['SourceKeyID'])
    # Include unapproved keys: a blocked key can collide after 32-bit truncation.
    all_candidate_owners = {}
    for r in prepared:
        for code in {r['_candidate'], r['_observed']} - {''}:
            all_candidate_owners.setdefault(code, set()).add(r.get('SourcePersonID',''))
    accepted = []; rejected = []
    for r in prepared:
        kid = r['SourceKeyID']; pid = r.get('SourcePersonID','')
        mark = source_marks[kid]
        reason = ''
        if expiry_column and not r.get('Срок действия','').strip():
            from migration_data import normalize_expiry
            if not any(k.casefold()==expiry_column.casefold() for k in mark):
                reason = 'Выбранное поле срока отсутствует в исходных ключах'
            else:
                try: r['Срок действия'] = normalize_expiry(value(mark, expiry_column))
                except ValueError as ex: reason = 'Срок: '+str(ex)
        if pid != value(mark,'Owner','OwnerID','Person') or r.get('RawCodeP','') != value(mark,'CodeP'):
            reason = 'Изменены исходные код или владелец'
        elif pid not in source_people: reason = 'Нет владельца в исходном pList'
        elif r.get('Approve','').strip().upper() != 'ДА': reason = 'Нет явного разрешения Approve=ДА'
        elif not r.get('ФИО','').strip(): reason = 'Не заполнено ФИО'
        # Observed per-key numbers bypass unsupported decoder, never identity checks.
        code = r['_observed']
        if not code:
            profile = r.get('Profile','').strip()
            if profile not in calibrated: reason = reason or profile_errors.get(profile,'Профиль не откалиброван')
            elif not r['_candidate']: reason = reason or r['_error']
            elif r['_upper'] not in calibrated_upper.get(profile,set()): reason = reason or 'Старшие байты отличаются от контрольных карт; нужна индивидуальная сверка'
            else: code = r['_candidate']
        if code and len(all_candidate_owners.get(code, set())) > 1:
            reason = 'Коллизия номера с другим владельцем (включая не одобренные ключи)'
        if r.get('Profile','').strip() in profile_errors and profile_errors[r.get('Profile','').strip()].startswith('Есть несовпадение'):
            reason = 'Профиль содержит несовпадение: остановлен целиком, включая ручные номера'
        if reason: rejected.append({**r,'Reason':reason})
        else: accepted.append({**r,'FinalW34':code})
    # Reject all participants of a collision or overflow, not only the last one.
    code_owners = {}; person_cards = {}; identities = {}; tabs = {}
    for r in accepted:
        pid = r['SourcePersonID']; code_owners.setdefault(r['FinalW34'],set()).add(pid)
        person_cards.setdefault(pid,set()).add(r['FinalW34'])
        if r['Табельный номер'].strip(): tabs.setdefault(r['Табельный номер'].strip(),set()).add(pid)
        identities.setdefault((r['ФИО'].strip().casefold(),r['Отдел'].strip().casefold()),set()).add(pid)
    final = []; seen = set(); duplicates = []
    for r in accepted:
        pid = r['SourcePersonID']; code = r['FinalW34']; reason = ''
        if len(code_owners[code]) > 1: reason = 'Один номер принадлежит нескольким людям'
        elif len(person_cards[pid]) > 5: reason = 'Больше пяти карт: выберите разрешённые, остальные Approve пусто'
        elif len(identities[(r['ФИО'].strip().casefold(),r['Отдел'].strip().casefold())]) > 1: reason = 'Разные SourcePersonID с одинаковыми ФИО/отделом: неоднозначность импорта'
        elif r['Табельный номер'].strip() and len(tabs[r['Табельный номер'].strip()])>1: reason = 'Повтор табельного номера у разных людей'
        elif (pid,code) in seen: reason = 'Повтор номера у одного человека: требуется ручное устранение дубля'
        if reason: rejected.append({**r,'Reason':reason})
        else: final.append(r); seen.add((pid,code))
    # A repeated card with different expiry must not select an arbitrary first row.
    counts = {}
    for r in accepted: counts[(r['SourcePersonID'],r['FinalW34'])] = counts.get((r['SourcePersonID'],r['FinalW34']),0)+1
    unique = []
    for r in final:
        if counts[(r['SourcePersonID'],r['FinalW34'])]>1: rejected.append({**r,'Reason':'Повтор номера у одного человека'})
        else: unique.append(r)
    final = unique
    from migration_data import enrich, export_xls, normalize_expiry
    details = enrich(source)
    # Reject invalid deadlines before accounting; preserve full time in raw CSV.
    valid = []
    for r in final:
        try:
            r['Срок действия'] = normalize_expiry(r.get('Срок действия',''))
            valid.append(r)
        except ValueError as ex: rejected.append({**r,'Reason':'Срок: '+str(ex)})
    final = valid
    out = source / ('result_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')); out.mkdir()
    write_csv(out/'Исключения.csv', rejected, REVIEW+['Reason'])
    write_csv(out/'Принятые.csv', final, REVIEW+['FinalW34'])
    report = {'complete':False, 'input_keys':len(rows),'accepted':len(final),'excluded':len(rejected),'calibrated_profiles':sorted(calibrated),'calibrated_upper_bytes':{k:sorted(v) for k,v in calibrated_upper.items()},'profile_errors':profile_errors,'note':'Фото и кадровые поля перенесены в файлы; исходные статусы/права не назначаются автоматически. Срок окончания только из явного поля/таблицы проверки. Начало действия и точное время требуют ручной настройки.'}
    (out/'Отчёт.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    assert len(final)+len(rejected)==len(rows)
    # All source people are also available without keys; no rights are assigned.
    staff_stats = export_xls(out/'Сотрудники_без_ключей.xls', details, source)
    card_stats = export_xls(out/'ТЕСТ_Импорт_Sigur.xls', details, source, final) if final else {}
    import shutil
    shutil.copy2(source/'Предупреждения_данных.csv',out/'Предупреждения_данных.csv')
    write_csv(out/'Данные_всех_ключей.csv', list(source_marks.values()), list(next(iter(source_marks.values()),{})))
    report['staff_file'] = staff_stats
    report['cards_file'] = card_stats
    report['complete'] = True
    (out/'Отчёт.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return out
