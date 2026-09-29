"""Personnel enrichment, photos and Sigur text-cell XLS output.
No SQL writes. Binary/technical source fields retained in the snapshot, not discarded.
"""
import base64, datetime, hashlib, io, json, re, shutil
from pathlib import Path

FIELD_RU = {
 'birthdate':'Дата рождения','datebirth':'Дата рождения','address':'Прописка',
 'pasportn':'Паспорт РФ','pasportnum':'Паспорт РФ','passportn':'Паспорт РФ',
 'dokumn':'Паспорт РФ','dokumnumber':'Паспорт РФ','dokumnos':'Паспорт РФ',
 'pasportdate':'Дата выдачи паспорта','dokumdate':'Дата выдачи паспорта',
 'pasportkem':'Кем выдан паспорт','pasportaddress':'Адрес регистрации',
 'datedocument':'Дата выдачи паспорта','kodpodr':'Код подразделения (паспорт)',
 'kem':'Кем выдан паспорт','email':'Электронная почта',
 'start':'Действует с (Орион)', 'sex':'Пол','phonehome':'Домашний телефон',
}

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
    if len(raw)<1000 and not raw.startswith(('\\\\','//')):
        candidate=Path(raw)
        if not candidate.is_absolute(): candidate=folder/candidate
        if candidate.is_file(): return candidate.read_bytes()
    raise ValueError('Фото: неизвестное представление или недоступный путь (UNC не читается)')

def enrich(folder):
    from safe_w34 import read_csv, value, write_csv
    folder=Path(folder); source=read_csv(folder/'pList.csv')
    meta=json.loads((folder/'schema.json').read_text(encoding='utf-8'))
    types={k.casefold():v for k,v in meta.get('tables',{}).get('pList',{}).get('columns',{}).items()}
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
    mapped={'id','name','surname','family','firstname','midname','middlename',
            'tabnumber','tab','tabel','post','position','company','firm','section','department',
            'phone','telephone','tel','mobile','picture','photo','foto','image'}
    technical={'uid','rowid','guid','guid_1c','status','shedule','schedule','spack','grstatus',
               'changetime','statuslist','gtype','config','operatorid','timeofcreation','fingerprint'}
    for p in source:
        pid=value(p,'ID')
        if not pid or pid in details: raise ValueError('pList.ID отсутствует или не уникален')
        comp=resolve(p,pid,('Company','Firm'),('PCompany','Company','Firm'))
        sect=resolve(p,pid,('Section','Department'),('PDivision','Section','pSection','Department'))
        post=resolve(p,pid,('Post','Position'),('PPost','Post','Posts','Position'))
        extra={}; birth=''
        for k,v in p.items():
            low=k.casefold()
            if low in mapped or low in technical or types.get(low) in ('image','binary','varbinary','timestamp','rowversion'):continue
            if not v:continue
            label=FIELD_RU.get(low,k)
            if label in extra: label=f'{label} ({k})'
            if low in ('birthdate','datebirth'):
                try:v=normalize_expiry(v)
                except ValueError:pass
                birth='Дата рождения: '+v
            extra[label]=v
        for field in ('Status','Schedule','Shedule','GrStatus'):
            v=value(p,field)
            if v:extra['Орион '+field+' (исходное значение)']=v
        if comp:extra['Компания']=comp
        if sect:extra['Подразделение']=sect
        for field in ('Company','Firm','Section','Department','Post','Position'):
            v=value(p,field)
            if v:extra['Орион '+field]=v
        d={'id':pid,'fio':' '.join(filter(None,[value(p,'Name','Surname','Family'),value(p,'FirstName'),value(p,'MidName','MiddleName')])),
           'tab':value(p,'TabNumber','Tab','Tabel'),'dept':', '.join(filter(None,[comp,sect])),
           'post':post,'phone':value(p,'Phone','Telephone','Tel','Mobile'),
           'note':birth,'extra':extra,'photo':''}
        picture=value(p,'Picture','Photo','Foto','Image')
        if picture:
            try:
                from PIL import Image,ImageOps
                data=photo_bytes(picture,folder)
                with Image.open(io.BytesIO(data)) as image:
                    image=ImageOps.exif_transpose(image).convert('RGB')
                    fn='person_'+hashlib.sha256(pid.encode()).hexdigest()+'.jpg'
                    image.save(photo_dir/fn,'JPEG',quality=92)
                    d['photo']='Фотографии\\'+fn
            except Exception as ex:
                warnings.append({'SourcePersonID':pid,'Field':'Фото','Reason':type(ex).__name__+': '+str(ex)[:200]})
        details[pid]=d
    (folder/'Персонал.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
    write_csv(folder/'Предупреждения_данных.csv',warnings,['SourcePersonID','Field','Reason'])
    return details


def export_xls(path, details, source, cards=None):
    """cards=None exports people only; all exact duplicates/homonyms quarantined."""
    from safe_w34 import write_csv
    import xlwt
    path=Path(path); source=Path(source); grouped={}; issues=[]
    if cards is None:
        for pid,p in details.items():
            grouped[pid]=[{'SourcePersonID':pid,'ФИО':p['fio'],'Отдел':p['dept'],'Должность':p['post'],'Табельный номер':p['tab'],'FinalW34':'','Срок действия':''}]
    else:
        for r in cards:grouped.setdefault(r['SourcePersonID'],[]).append(r)
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
    extra_cols=sorted({k for pid in selected for k in details[pid]['extra']})
    cols=['ФИО','Отдел','Должность','Номер пропуска','Срок действия','Табельный номер','Тип пропуска',
          'Номер телефона','Тип записи','Имя файла фотографии','Примечание','Орион ID']
    if len(cols)+len(extra_cols)>256:raise ValueError('Превышен лимит колонок XLS, требуется явный выбор полей')
    wb=xlwt.Workbook();ws=wb.add_sheet('Импорт');style=xlwt.easyxf('align: wrap on, vert top',num_format_str='@')
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
            vals=[r['ФИО'],r['Отдел'],r['Должность'],r['FinalW34'],r.get('Срок действия',''),r['Табельный номер'],'Карта' if r['FinalW34'] else '',person['phone'],'Сотрудник',photo,person['note'],pid]+[person['extra'].get(k,'') for k in extra_cols]
            if j:vals=['','','',r['FinalW34'],r.get('Срок действия',''),'','Карта']+['']*(len(cols)+len(extra_cols)-7)
            for i,v in enumerate(vals):
                if len(str(v))>32767:raise ValueError(f'Слишком длинное поле: {pid}, {cols[i] if i<len(cols) else extra_cols[i-len(cols)]}')
                ws.write(idx,i,str(v),style)
            idx+=1
    if selected:
        tmp=path.with_suffix('.tmp');wb.save(str(tmp));tmp.replace(path)
    write_csv(path.with_name(path.stem+'_исключения.csv'),issues,['SourcePersonID','Reason'])
    return {'people':len(selected),'rows':rows_count,'photos':photos,'excluded_people':len(issues),'file_created':bool(selected)}
