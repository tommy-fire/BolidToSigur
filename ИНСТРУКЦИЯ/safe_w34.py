"""Строгая W34-миграция с офлайн-проверками. Без записей в исходную и целевую БД.
Раскладка CodeP из сообщества — поддерживаемая гипотеза, а не универсальный формат Болид.
"""
import csv, json, re, os, datetime, importlib.machinery, importlib.util
from pathlib import Path

# Фото в HEX могут превышать полевой лимит CSV-парсера.
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
    """Переиспользуем найденное подключение; в каждом результате фиксируем реально успешную аутентификацию."""
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
    """Каждую таблицу выгружаем независимо, сохраняем осиротевшие записи и бинарные поля."""
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
                # Сериализуем varchar CodeP на стороне сервера, без лишних преобразований через Unicode.
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
    # Исходная выгрузка полная, даже если при обогащении встретятся неподдерживаемые поля.
    from migration_data import enrich
    enrich(dest)
    return dest

def value(row, *names):
    low = {k.lower():v for k,v in row.items()}
    return next((low[n.lower()] for n in names if n.lower() in low), '')

REVIEW = ['SourceKeyID','SourcePersonID','ФИО','Табельный номер','Отдел','Должность','RawCodeP','Format','ABD','CandidateW34','DecodeError','Profile','ObservedW34','Approve','Срок действия','SourceMetadata','Исходный срок','Поле срока','Начало действия пропуска']

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
        result[-1]['Начало действия пропуска'] = ''
        # Храним как метаданные; является ли это сроком окончания — решает пользователь.
    target = folder/'Проверка.csv'
    if target.exists(): raise ValueError('Проверка.csv уже существует: не перезаписываю вашу проверку')
    write_csv(target,result,REVIEW)
    return target

def build(review_path, expiry_column='', start_column='', personal_mode='fields', allow_multicard_dates=False, candidate_draft=False, trial_import=False):
    """Строгий путь требует подтверждения; явный пробный режим выдаёт несверенные тестовые кандидаты."""
    if candidate_draft and trial_import:raise ValueError('Выберите один режим подготовки')
    automatic = candidate_draft or trial_import
    if candidate_draft and allow_multicard_dates:raise ValueError('В автоматическом черновике нельзя обходить проверку нескольких карт')
    if expiry_column and start_column and expiry_column.casefold()==start_column.casefold():raise ValueError('Начало и окончание не могут быть одним полем')
    review_path = Path(review_path); rows = read_csv(review_path)
    profiles = {}; prepared = []; ids = set()
    for r in rows:
        kid = r.get('SourceKeyID','').strip()
        if not kid or kid in ids: raise ValueError('Пустой/повторный SourceKeyID')
        ids.add(kid)
        # Состав записей должен соответствовать неизменённой исходной выгрузке.
        r['_candidate'] = ''; r['_error'] = ''; r['_upper'] = ''
        try:
            abd,r['_candidate'] = decode(r.get('RawCodeP',''),r.get('Format','raw'))
            r['_upper'] = abd[2:6]
        except ValueError as ex: r['_error'] = str(ex)
        if automatic:
            # Автоматический пробный импорт никогда не наследует подтверждения оператора или калибровку.
            r['Approve']=r['ObservedW34']=r['Profile']=''
            r['Срок действия']=r['Начало действия пропуска']=''
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
    # Включаем неподтверждённые ключи: заблокированный ключ тоже может вступить в коллизию после усечения до 32 бит.
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
            from migration_data import normalize_access
            if not any(k.casefold()==expiry_column.casefold() for k in mark):
                reason = 'Выбранное поле срока отсутствует в исходных ключах'
            else:
                try: r['Срок действия'] = normalize_access(value(mark, expiry_column))
                except ValueError as ex: reason = 'Срок: '+str(ex)
        if start_column and not r.get('Начало действия пропуска','').strip():
            from migration_data import normalize_access
            if not any(k.casefold()==start_column.casefold() for k in mark):reason = 'Поле начала отсутствует'
            else:
                try:r['Начало действия пропуска']=normalize_access(value(mark,start_column))
                except ValueError as ex:reason='Начало: '+str(ex)
        if pid != value(mark,'Owner','OwnerID','Person') or r.get('RawCodeP','') != value(mark,'CodeP'):
            reason = 'Изменены исходные код или владелец'
        elif pid not in source_people: reason = 'Нет владельца в исходном pList'
        elif not automatic and r.get('Approve','').strip().upper() != 'ДА': reason = 'Нет явного разрешения Approve=ДА'
        elif not r.get('ФИО','').strip(): reason = 'Не заполнено ФИО'
        # Наблюдаемые номера по ключам обходят неподдерживаемый декодер, но не проверки состава.
        code = r['_candidate'] if automatic else r['_observed']
        if automatic:
            if r.get('DecodeError'):reason=reason or r['DecodeError']
            if not code:reason = reason or r['_error'] or 'Не удалось разобрать исходный номер'
            if candidate_draft and (not start_column or not expiry_column):reason = reason or 'Не удалось однозначно найти оба поля срока карты'
            if candidate_draft and (not r.get('Начало действия пропуска') or not r.get('Срок действия')):reason = reason or 'Пустая граница срока: нужно подтвердить её смысл'
        elif not code:
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
    # Отклоняем всех участников коллизии или переполнения, а не только последнего.
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
    # Повторившаяся карта с другим сроком не должна попадаться по первой попавшейся строке.
    counts = {}
    for r in accepted: counts[(r['SourcePersonID'],r['FinalW34'])] = counts.get((r['SourcePersonID'],r['FinalW34']),0)+1
    unique = []
    for r in final:
        if counts[(r['SourcePersonID'],r['FinalW34'])]>1: rejected.append({**r,'Reason':'Повтор номера у одного человека'})
        else: unique.append(r)
    final = unique
    from migration_data import enrich, export_xls, normalize_access
    details = enrich(source)
    # Некорректные сроки отклоняем до подсчёта; полное время сохраняем в сыром CSV.
    valid = []
    for r in final:
        try:
            r['Срок действия'] = normalize_access(r.get('Срок действия',''))
            r['Начало действия пропуска'] = normalize_access(r.get('Начало действия пропуска',''))
            if r['Срок действия'] and r['Начало действия пропуска'] and datetime.datetime.strptime(r['Начало действия пропуска'],'%d.%m.%Y %H:%M:%S') >= datetime.datetime.strptime(r['Срок действия'],'%d.%m.%Y %H:%M:%S'):raise ValueError('Начало должно быть раньше окончания')
            valid.append(r)
        except ValueError as ex: rejected.append({**r,'Reason':'Срок: '+str(ex)})
    final = valid
    excluded_staff=[]
    if automatic:
        identity_owners={};tab_owners={}
        for pid,p in details.items():
            identity_owners.setdefault((p['fio'].strip().casefold(),p['dept'].strip().casefold()),set()).add(pid)
            if p['tab'].strip():tab_owners.setdefault(p['tab'].strip(),set()).add(pid)
        bad=set()
        for pid,p in details.items():
            reason=''
            if not p['fio'].strip():reason='Пустое ФИО'
            elif len(identity_owners[(p['fio'].strip().casefold(),p['dept'].strip().casefold())])>1:reason='Неоднозначные ФИО и отдел'
            elif p['tab'].strip() and len(tab_owners[p['tab'].strip()])>1:reason='Неоднозначный табельный номер'
            if reason:bad.add(pid);excluded_staff.append({'Орион ID':pid,'ФИО':p['fio'],'Причина':reason})
        allowed=[]
        for r in final:
            if r['SourcePersonID'] in bad:rejected.append({**r,'Reason':'Неоднозначная кадровая карточка'})
            else:allowed.append(r)
        final=allowed;details={pid:p for pid,p in details.items() if pid not in bad}
    # По датам в строках продолжения руководства неоднозначны. По умолчанию — консервативно: исключаем.
    if not allow_multicard_dates and not trial_import:
        dated_people={r['SourcePersonID'] for r in final if r.get('Срок действия') or r.get('Начало действия пропуска')}
        totals={}
        for r in final:totals[r['SourcePersonID']]=totals.get(r['SourcePersonID'],0)+1
        allowed=[]
        for r in final:
            if r['SourcePersonID'] in dated_people and totals[r['SourcePersonID']]>1:
                rejected.append({**r,'Reason':'Несколько карт со сроками: сначала требуется отдельный тест строк продолжения в установленной версии Sigur'})
            else:allowed.append(r)
        final=allowed
    if candidate_draft:
        for p in details.values():p['dept']='ТЕСТ — НЕ НАЗНАЧАТЬ ДОСТУП'+(', '+p['dept'] if p['dept'] else '')
        for r in final:r['Отдел']=details[r['SourcePersonID']]['dept']
    out = source / ('result_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')); out.mkdir()
    write_csv(out/'Исключения.csv', rejected, REVIEW+['Reason'])
    if candidate_draft:
        write_csv(out/'КАРТЫ_ТОЛЬКО_СВЕРКА_НЕ_ИМПОРТ.csv',[{'ID ключа':r['SourceKeyID'],'ID владельца':r['SourcePersonID'],'ФИО':r['ФИО'],'Исходный CodeP':r['RawCodeP'],'НЕПОДТВЕРЖДЁННЫЙ кандидат W34':'НЕПОДТВЕРЖДЁН:'+r['FinalW34'],'Начало — сверить':r.get('Начало действия пропуска',''),'Окончание — сверить':r.get('Срок действия',''),'Назначение':'ТОЛЬКО СВЕРКА, НЕ ИМПОРТ; raw08-dallas01-low32; физических совпадений: 0'} for r in final],['ID ключа','ID владельца','ФИО','Исходный CodeP','НЕПОДТВЕРЖДЁННЫЙ кандидат W34','Начало — сверить','Окончание — сверить','Назначение'])
    elif trial_import:write_csv(out/'КАРТЫ_ПРОБНОГО_ИМПОРТА.csv',final,REVIEW+['FinalW34'])
    else:write_csv(out/'Принятые.csv', final, REVIEW+['FinalW34'])
    report = {'complete':False, 'input_keys':len(rows),'accepted':len(final),'excluded':len(rejected),'calibrated_profiles':sorted(calibrated),'calibrated_upper_bytes':{k:sorted(v) for k,v in calibrated_upper.items()},'profile_errors':profile_errors,'note':'Фото и кадровые поля перенесены в файлы; исходные статусы/права не назначаются автоматически. Срок окончания только из явного поля/таблицы проверки. Начало и окончание с точным временем берутся только из явно выбранных полей. Режим Турникет — 24/7 назначается в Sigur отдельно.'}
    (out/'Отчёт.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    assert len(final)+len(rejected)==len(rows)
    # Все сотрудники из источника доступны и без ключей; права не назначаются.
    if candidate_draft:
        card_name='Для_Sigur_СОТРУДНИКИ_БЕЗ_КАРТ.xls'
        card_stats=export_xls(out/card_name,details,source,final,personal_mode=personal_mode,experimental=True,include_cardless=True,draft_marker=True)
        staff_stats={}
        write_csv(out/'Сотрудники_исключения.csv',excluded_staff,['Орион ID','ФИО','Причина'])
        report['excluded_staff']=len(excluded_staff)
    elif trial_import:
        card_name='ПРОБНЫЙ_ПОЛНЫЙ_Импорт_Sigur.xls'
        card_stats=export_xls(out/card_name,details,source,final,personal_mode=personal_mode,include_cardless=True,trial_marker=True)
        staff_stats={}
        write_csv(out/'Сотрудники_исключения.csv',excluded_staff,['Орион ID','ФИО','Причина'])
        report['excluded_staff']=len(excluded_staff)
    else:
        staff_stats = export_xls(out/'Сотрудники_без_ключей.xls', details, source, personal_mode=personal_mode)
        card_name='ДИАГНОСТИКА_НЕ_ДЛЯ_РАБОТЫ.xls' if allow_multicard_dates else 'ТЕСТ_Импорт_Sigur.xls'
        card_stats = export_xls(out/card_name, details, source, final, personal_mode=personal_mode, experimental=allow_multicard_dates) if final else {}
    checklist=[]
    for r in final+rejected:
        checklist.append({'ID ключа':r['SourceKeyID'],'ID сотрудника':r['SourcePersonID'],'ФИО':r.get('ФИО',''),'Номер W34':(('НЕПОДТВЕРЖДЁН:'+r.get('_candidate','')) if candidate_draft else (r.get('FinalW34') or r.get('_observed') or r.get('_candidate',''))),'Статус номера':('НЕПОДТВЕРЖДЁННЫЙ КАНДИДАТ' if automatic else 'Принят') if not r.get('Reason') else 'НЕ ПЕРЕНОСИТЬ БЕЗ ПРОВЕРКИ','Начало':r.get('Начало действия пропуска',''),'Окончание':r.get('Срок действия',''),'Причина':r.get('Reason',''),'Имя и номер проверены в Sigur':'','Обе даты проверены в Sigur':'','Права проверены на турникете':''})
    if checklist:write_csv(out/'Сверка_каждой_карты.csv',checklist,list(checklist[0]))
    import shutil
    shutil.copy2(source/'Предупреждения_данных.csv',out/'Предупреждения_данных.csv')
    write_csv(out/'Данные_всех_ключей.csv', list(source_marks.values()), list(next(iter(source_marks.values()),{})))
    report['source_start_column']=start_column
    report['source_end_column']=expiry_column
    report['test_only']=True
    report['candidate_draft']=candidate_draft
    report['trial_import']=trial_import
    report['hardware_verified']=False
    report['source_statuses_verified']=False
    report['access_rights_assigned']=False
    report['personal_mode']=personal_mode
    report['experimental_multicard_dates']=allow_multicard_dates
    report['warnings']=['До выдачи доступа проверьте оба срока каждой карты, особенно второй и последующих: руководство неоднозначно описывает даты в строках продолжения.', 'Режим Турникет — 24/7 назначить отдельно; комнату охраны не включать.', 'Пустое окончание может означать бессрочность; пустое начало Sigur может заменить временем импорта.']
    report['staff_file'] = staff_stats
    report['cards_file'] = card_stats
    report['cards_filename']=card_name
    if candidate_draft:
        report['draft_candidates']=report.pop('accepted')
        report['calibrated_profiles']=[]
        report['calibrated_upper_bytes']={}
        report['note']='Автоматический ЧЕРНОВИК. Номера, исходные статусы и смысл дат НЕ подтверждены. Только пустая изолированная тестовая база без назначения доступа. Это не готовый рабочий перенос.'
    if trial_import:
        report['trial_cards']=report.pop('accepted')
        report['calibrated_profiles']=[]
        report['calibrated_upper_bytes']={}
        report['number_hypothesis']='raw08-dallas01-low32'
        report['note']='ПРОБНЫЙ ПОЛНЫЙ ИМПОРТ: номера — расчётные кандидаты W34, не сверенные физически; даты из найденных полей; блокировки и права НЕ перенесены. Только пустая изолированная тестовая база без доступа.'
    report['complete'] = True
    (out/'Отчёт.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return out
