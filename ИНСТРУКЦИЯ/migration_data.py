"""Personnel enrichment, photos and Sigur text-cell XLS output.
No SQL writes. Binary/technical source fields retained in the snapshot, not discarded.
"""
import base64, datetime, hashlib, io, json, re, shutil
from pathlib import Path

def normalize_expiry(raw):
    raw=str(raw or '').strip()
    if not raw: return ''
    for fmt in ('%d.%m.%Y','%Y-%m-%d','%d/%m/%Y'):
        try: return datetime.datetime.strptime(raw,fmt).strftime('%d.%m.%Y')
        except ValueError: pass
    try: dt=datetime.datetime.fromisoformat(raw)
    except ValueError: raise ValueError('Неизвестная дата, требуется ДД.ММ.ГГГГ')
    if dt.time()!=datetime.time() or dt.tzinfo:
        raise ValueError('Есть время/часовой пояс: настройте срок вручную, не округляйте')
    return dt.strftime('%d.%m.%Y')

def normalize_access(raw):
    """Exact local date/time; no implicit timezone conversion or rounding."""
    raw=str(raw or '').strip()
    if not raw:return ''
    for fmt in ('%d.%m.%Y %H:%M:%S','%d.%m.%Y %H:%M','%Y-%m-%d %H:%M:%S','%d.%m.%Y','%Y-%m-%d'):
        try:return datetime.datetime.strptime(raw,fmt).strftime('%d.%m.%Y %H:%M:%S')
        except ValueError:pass
    try:dt=datetime.datetime.fromisoformat(raw)
    except ValueError:raise ValueError('Неизвестная дата/время')
    if dt.tzinfo or dt.microsecond:raise ValueError('Часовой пояс/доли секунды требуют явного решения')
    return dt.strftime('%d.%m.%Y %H:%M:%S')

def agreed_personal(p, warnings, pid):
    from safe_w34 import value
    birth=value(p,'BirthDate','DateBirth'); passport=value(p,'PasportN','PasportNum','PassportN','DokumN','DokumNumber','DokumNos')
    parts=[]
    for label,fields in [('Выдан',('PasportDate','DokumDate','DateDocument')),('Кем выдан',('PasportKem','Kem')),('Код подразделения',('KodPodr',))]:
        v=value(p,*fields)
        if v:parts.append(label+': '+v)
    passport='; '.join(filter(None,[passport]+parts))
    address=value(p,'Address','PasportAddress')
    note=value(p,'Note','Notes','Comment','Comments','Remark','Remarks','Примечание','Примечания')
    found={}
    duplicates=set()
    for line in note.splitlines():
        m=re.fullmatch(r'\s*(Дата рождения|Паспорт РФ|Прописка)\s*:\s*(.*?)\s*',line,re.I)
        if m:
            label=m[1].lower()
            if label in found and found[label]!=m[2]:
                warnings.append({'SourcePersonID':pid,'Field':'Примечание','Reason':'Повтор разных значений: '+label})
                duplicates.add(label)
                found[label]=''
            elif label not in duplicates:found[label]=m[2]
    conflicts=set()
    vals=[birth,passport,address]
    for i,label in enumerate(('дата рождения','паспорт рф','прописка')):
        if vals[i] and found.get(label) and vals[i]!=found[label]:
            conflicts.add(i)
            warnings.append({'SourcePersonID':pid,'Field':label,'Reason':'Разные значения в отдельном поле и примечании; дополнительное поле не заполнено, требуется сверка'})
        vals[i]=vals[i] or found.get(label,'')
    if vals[0]:
        try:vals[0]=normalize_expiry(vals[0])
        except ValueError:
            warnings.append({'SourcePersonID':pid,'Field':'Дата рождения','Reason':'Не распознана дата; оставлена в примечании, поле даты пустое'})
    if note and not found and not vals[0]:
        warnings.append({'SourcePersonID':pid,'Field':'Примечание','Reason':'Не удалось выделить дату рождения; исходный текст сохранён для сверки'})
    try:date=normalize_expiry(vals[0])
    except ValueError:date=''
    extra={k:v for k,v in zip(('Дата рождения','Паспорт РФ','Прописка'),(date,vals[1],vals[2])) if v}
    fallback='\n'.join(k+': '+v for k,v in zip(('Дата рождения','Паспорт РФ','Прописка'),vals))
    for i,label in enumerate(('Дата рождения','Паспорт РФ','Прописка')):
        if i in conflicts:extra.pop(label,None)
    for label in duplicates:
        extra.pop({'дата рождения':'Дата рождения','паспорт рф':'Паспорт РФ','прописка':'Прописка'}[label],None)
    if 'Дата рождения' in extra:
        dt=datetime.datetime.strptime(extra['Дата рождения'],'%d.%m.%Y').date()
        if dt>datetime.date.today():
            extra.pop('Дата рождения')
            warnings.append({'SourcePersonID':pid,'Field':'Дата рождения','Reason':'Будущая дата: оставлена только в примечании для сверки'})
    if note:
        warnings.append({'SourcePersonID':pid,'Field':'Примечание','Reason':'Проверьте извлечение кадровых данных из примечания по исходному тексту'})
    if note:fallback+='\nИсходное примечание Болид: '+note
    return extra,fallback

def expiry_candidate(row):
    # Exact field-name suggestions only, never arbitrary date-content matching.
    names=('finish','validuntil','enddate','dateend','expiredate','expirationdate')
    hits=[(k,v) for k,v in row.items() if k.casefold() in names]
    return hits[0] if len(hits)==1 else ('','')

def photo_bytes(raw, folder):
    raw=str(raw or '').strip()
    if not raw: return b''
    # Decode embedded image first. External paths are read only if file exists;
    # UNC paths are deliberately not opened (avoid leaking network credentials).
    if re.fullmatch('[0-9A-Fa-f]+',raw) and len(raw)%2==0:
        return bytes.fromhex(raw)
    if len(raw)>40 and (raw.startswith('data:image/') or re.fullmatch(r'[A-Za-z0-9+/=\s]+',raw)):
        try: return base64.b64decode(raw.split(',',1)[-1],validate=True)
        except Exception: pass
    if not (folder/'PORTABLE.txt').exists() and len(raw)<1000 and not raw.startswith(('\\\\','//')):
        candidate=Path(raw)
        if not candidate.is_absolute(): candidate=folder/candidate
        if candidate.is_file(): return candidate.read_bytes()
    raise ValueError('Фото: неизвестное представление или недоступный путь (UNC не читается)')

def enrich(folder):
    from safe_w34 import read_csv, value, write_csv
    folder=Path(folder); source=read_csv(folder/'pList.csv')
    references={}; warnings=[]
    for name in ('PCompany','PDivision','PPost','Company','Firm','Section','pSection','Department','Post','Posts','Position'):
        if (folder/(name+'.csv')).exists():
            d={}
            for row in read_csv(folder/(name+'.csv')):
                key=value(row,'ID'); nameval=value(row,'Name')
                if key in d: warnings.append({'SourcePersonID':'','Field':name,'Reason':'Повтор ID справочника'}); d[key]=''
                else: d[key]=nameval
            references[name]=d
    def resolve(p,pid,fields,tables):
        v=value(p,*fields).strip()
        if not v: return ''
        if not re.fullmatch(r'[+-]?\d+',v): return v
        for table in tables:
            if references.get(table,{}).get(v): return references[table][v]
        warnings.append({'SourcePersonID':pid,'Field':fields[0],'Reason':f'Не найдено название для ID={v}; исходный ID сохранён'})
        return ''
    details={}; photo_dir=folder/'Фотографии'; photo_dir.mkdir(exist_ok=True)
    cache_path=folder/'photo_cache.json'
    try:old_cache=json.loads(cache_path.read_text(encoding='utf-8'))
    except (OSError,ValueError):old_cache={}
    if not isinstance(old_cache,dict):old_cache={}
    new_cache={}
    for p in source:
        pid=value(p,'ID')
        if not pid or pid in details: raise ValueError('pList.ID отсутствует или не уникален')
        comp=resolve(p,pid,('Company','Firm'),('PCompany','Company','Firm'))
        sect=resolve(p,pid,('Section','Department'),('PDivision','Section','pSection','Department'))
        post=resolve(p,pid,('Post','Position'),('PPost','Post','Posts','Position'))
        d={'id':pid,'fio':' '.join(filter(None,[value(p,'Name','Surname','Family'),value(p,'FirstName'),value(p,'MidName','MiddleName')])),
           'tab':value(p,'TabNumber','Tab','Tabel'),'dept':', '.join(filter(None,[comp,sect])),
           'post':post,'note':'','extra':{},'photo':''}
        d['extra'], d['note'] = agreed_personal(p,warnings,pid)
        picture=value(p,'Picture','Photo','Foto','Image')
        if picture:
            try:
                from PIL import Image,ImageOps
                fn='person_'+hashlib.sha256(pid.encode()).hexdigest()+'.jpg'
                src_hash=hashlib.sha256(picture.encode('utf-8')).hexdigest()
                cached=old_cache.get(pid,{})
                photo=photo_dir/fn
                reused=False
                if isinstance(cached,dict) and cached.get('source_sha256')==src_hash and photo.is_file() and not photo.is_symlink():
                    data=photo.read_bytes()
                    if hashlib.sha256(data).hexdigest()==cached.get('photo_sha256'):
                        with Image.open(io.BytesIO(data)) as image:image.verify()
                        reused=True
                if not reused:
                    data=photo_bytes(picture,folder)
                    with Image.open(io.BytesIO(data)) as image:
                        image=ImageOps.exif_transpose(image).convert('RGB')
                        image.save(photo,'JPEG',quality=92)
                d['photo']='Фотографии\\'+fn
                new_cache[pid]={'source_sha256':src_hash,'photo_sha256':hashlib.sha256(photo.read_bytes()).hexdigest()}
            except Exception as ex:
                warnings.append({'SourcePersonID':pid,'Field':'Фото','Reason':type(ex).__name__+': '+str(ex)[:200]})
        details[pid]=d
    cache_path.write_text(json.dumps(new_cache,ensure_ascii=False),encoding='utf-8')
    (folder/'Персонал.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
    write_csv(folder/'Предупреждения_данных.csv',warnings,['SourcePersonID','Field','Reason'])
    return details


def export_xls(path, details, source, cards=None, personal_mode='fields', experimental=False, include_cardless=False, draft_marker=False):
    if personal_mode not in ('fields','notes'):raise ValueError('Неизвестный режим кадровых полей')
    """cards=None exports people only; all exact duplicates/homonyms quarantined."""
    from safe_w34 import write_csv
    import xlwt
    path=Path(path); source=Path(source); grouped={}; issues=[]
    if cards is not None and not draft_marker:
        for r in cards:grouped.setdefault(r['SourcePersonID'],[]).append(r)
    if cards is None or include_cardless:
        for pid,p in details.items():
            if pid in grouped:continue
            grouped[pid]=[{'SourcePersonID':pid,'ФИО':p['fio'],'Отдел':p['dept'],'Должность':p['post'],'Табельный номер':p['tab'],'FinalW34':'','Срок действия':''}]
    identities={}; tabs={}
    for pid,rows in grouped.items():
        row=rows[0];identities.setdefault((row['ФИО'].strip().casefold(),row['Отдел'].strip().casefold()),set()).add(pid)
        if row['Табельный номер'].strip():tabs.setdefault(row['Табельный номер'].strip(),set()).add(pid)
    selected={}
    for pid,rows in grouped.items():
        r=rows[0]; reason=''
        if not r['ФИО'].strip():reason='Пустое ФИО'
        elif len(identities[(r['ФИО'].strip().casefold(),r['Отдел'].strip().casefold())])>1:reason='Одинаковые ФИО/отдел у разных людей'
        elif r['Табельный номер'].strip() and len(tabs[r['Табельный номер'].strip()])>1:reason='Повтор табельного номера'
        if reason:
            if cards is not None:raise ValueError(reason+': '+pid)
            issues.append({'SourcePersonID':pid,'Reason':reason})
        else:selected[pid]=rows
    rows_count=sum(len(r) for r in selected.values())
    if rows_count>65535:raise ValueError('Превышен лимит строк XLS; нужна разбивка')
    extra_cols=['Дата рождения','Паспорт РФ','Прописка'] if personal_mode=='fields' else []
    cols=['ФИО','Отдел','Должность','Номер пропуска','Окончание действия пропуска','Табельный номер','Тип пропуска',
          'Тип записи','Имя файла фотографии','Примечание','Орион ID','Начало действия пропуска']
    if len(cols)+len(extra_cols)>256:raise ValueError('Превышен лимит колонок XLS, требуется явный выбор полей')
    wb=xlwt.Workbook();ws=wb.add_sheet('ДИАГНОСТИКА' if experimental else 'Импорт');style=xlwt.easyxf('align: wrap on, vert top',num_format_str='@')
    hdr=xlwt.easyxf('font: bold on',num_format_str='@')
    for i,h in enumerate(cols+extra_cols):ws.write(0,i,h,hdr);ws.col(i).width=6500
    idx=1;photos=0
    for pid,rows in selected.items():
        person=details[pid];ident={(r['ФИО'],r['Отдел'],r['Должность'],r['Табельный номер']) for r in rows}
        if len(ident)!=1:raise ValueError('Разные кадровые поля у одного SourcePersonID: '+pid)
        photo=person['photo']
        if photo:
            (path.parent/'Фотографии').mkdir(exist_ok=True)
            shutil.copy2(source/Path(photo.replace('\\','/')),path.parent/Path(photo.replace('\\','/')));photos+=1
        for j,r in enumerate(rows):
            vals=[r['ФИО'],r['Отдел'],r['Должность'],r['FinalW34'],r.get('Срок действия',''),r['Табельный номер'],'Карта' if r['FinalW34'] else '','Сотрудник',photo,((person['note'] if personal_mode=='notes' or draft_marker else '')+('\nТЕСТ. Номера карт и статусы НЕ ПРОВЕРЕНЫ. НЕ НАЗНАЧАТЬ ДОСТУП.' if draft_marker else '')),pid,r.get('Начало действия пропуска','')]+[person['extra'].get(k,'') for k in extra_cols]
            if j:
                vals=['']*(len(cols)+len(extra_cols))
                for field,val in [('Номер пропуска',r['FinalW34']),('Тип пропуска','Карта'),('Окончание действия пропуска',r.get('Срок действия','')),('Начало действия пропуска',r.get('Начало действия пропуска',''))]:vals[cols.index(field)]=val
            for i,v in enumerate(vals):
                if len(str(v))>32767:raise ValueError(f'Слишком длинное поле: {pid}, {cols[i] if i<len(cols) else extra_cols[i-len(cols)]}')
                ws.write(idx,i,str(v),style)
            idx+=1
    if selected:
        tmp=path.with_suffix('.tmp');wb.save(str(tmp));tmp.replace(path)
    write_csv(path.with_name(path.stem+'_исключения.csv'),issues,['SourcePersonID','Reason'])
    return {'people':len(selected),'rows':rows_count,'photos':photos,'excluded_people':len(issues),'file_created':bool(selected)}
