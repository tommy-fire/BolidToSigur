"""Портативные .bolid-архивы: офлайн, с версией, ограничены по размеру, не исполняемые.
SHA256 обнаруживает повреждение, но НЕ является подписью и не доказывает автора файла.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

FORMAT = 'BolidToSigur.transfer'
VERSION = 1
MANIFEST = 'manifest.json'
MAX_FILES = 100000
MAX_TOTAL = 4 * 1024**3
MAX_FILE = 2 * 1024**3
MAX_MANIFEST = 32 * 1024**2
REQUIRED = {'pList.csv', 'pMark.csv', 'schema.json', 'COMPLETE.txt', 'Проверка.csv'}
TABLES = {'pList','pMark','PCompany','PDivision','PPost','Company','Firm','Section','pSection','Department','Post','Posts','Position'}
ALLOWED = REQUIRED | {t+'.csv' for t in TABLES} | {'photo_cache.json'}
PHOTO = re.compile(r'Фотографии/person_[0-9a-f]{64}\.jpg')


def safe_name(name):
    return isinstance(name, str) and (name in ALLOWED or PHOTO.fullmatch(name) is not None)


def digest_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def validate_snapshot(folder):
    from safe_w34 import read_csv, value
    folder = Path(folder)
    if not all((folder/n).is_file() for n in REQUIRED):
        raise ValueError('Не хватает исходных файлов. Нужна завершённая выгрузка нашей программы.')
    meta = json.loads((folder/'schema.json').read_text(encoding='utf-8'))
    if not {'pList','pMark'} <= set(meta.get('tables', {})):
        raise ValueError('В schema.json нет описания pList/pMark')
    people = read_csv(folder/'pList.csv'); marks = read_csv(folder/'pMark.csv'); rows = read_csv(folder/'Проверка.csv')
    for name, records in [('pList', people), ('pMark', marks)]:
        ids = [value(r,'ID') for r in records]
        if any(not k for k in ids) or len(ids) != len(set(ids)):
            raise ValueError(name+': пустой/повторный ID')
        count = meta['tables'][name].get('rows')
        if count is not None and count != len(records):
            raise ValueError(name+': число строк не совпадает со схемой')
    by_id = {value(m,'ID'):m for m in marks}
    review_ids = [r.get('SourceKeyID','') for r in rows]
    if len(review_ids) != len(set(review_ids)) or set(review_ids) != set(by_id):
        raise ValueError('Состав ключей в Проверка.csv отличается от исходного pMark.csv')
    for r in rows:
        m = by_id[r['SourceKeyID']]
        if r.get('RawCodeP') != value(m,'CodeP') or r.get('SourcePersonID') != value(m,'Owner','OwnerID','Person') or r.get('Format') != 'raw':
            raise ValueError('Изменены исходный код/владелец/формат ключа '+r['SourceKeyID'])
    return {'people':len(people), 'keys':len(marks)}


def clean_settings(settings):
    settings = settings or {}
    result = {}
    for key in ('start_column','expiry_column'):
        v = settings.get(key, '')
        if not isinstance(v,str) or len(v)>256: raise ValueError('Некорректное имя поля срока')
        result[key] = v
    mode = settings.get('personal_mode', 'fields')
    if mode not in ('fields','notes'): raise ValueError('Неизвестный режим кадровых полей')
    result['personal_mode'] = mode
    # Диагностические переопределения НИКОГДА не запоминаются в портативном файле.
    return result


def pack(folder, destination, settings=None):
    """Создаём атомарно. Без доступа к БД, папок результата и учётных данных."""
    folder=Path(folder); destination=Path(destination)
    if destination.suffix.lower() != '.bolid': raise ValueError('Файл должен иметь расширение .bolid')
    counts=validate_snapshot(folder)
    from migration_data import enrich
    details=enrich(folder)  # кэшируем фото, чтобы файл можно было перенести на другой компьютер
    files=[]
    for name in sorted(ALLOWED):
        p=folder/name
        if p.is_symlink(): raise ValueError('Ссылки не допускаются: '+name)
        if p.is_file(): files.append((name,p))
    photo_dir=folder/'Фотографии'
    if photo_dir.is_symlink(): raise ValueError('Каталог фото не может быть ссылкой')
    if photo_dir.exists():
        used={p['photo'].replace('\\','/') for p in details.values() if p.get('photo')}
        for p in sorted(photo_dir.iterdir()):
            if 'Фотографии/'+p.name not in used:continue
            if PHOTO.fullmatch('Фотографии/'+p.name):
                if p.is_symlink() or not p.is_file(): raise ValueError('Некорректный файл фото')
                files.append(('Фотографии/'+p.name,p))
    total=sum(p.stat().st_size for _,p in files)
    if len(files)>MAX_FILES or total>MAX_TOTAL or any(p.stat().st_size>MAX_FILE for _,p in files):
        raise ValueError('Слишком большая выгрузка: лимит 4 ГиБ суммарно / 2 ГиБ на файл / 100000 файлов')
    manifest={'format':FORMAT,'version':VERSION,'created':datetime.datetime.now().isoformat(timespec='seconds'),
              'counts':counts,'settings':clean_settings(settings),'files':{}}
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+destination.name+'.',suffix='.tmp',dir=destination.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
            for name,p in files:
                h=hashlib.sha256(); size=0
                with open(p,'rb') as src, z.open(name,'w',force_zip64=True) as dest:
                    for chunk in iter(lambda:src.read(1024*1024),b''):
                        size+=len(chunk); h.update(chunk); dest.write(chunk)
                        if size>MAX_FILE: raise ValueError('Размер файла изменился при упаковке')
                manifest['files'][name]={'size':size,'sha256':h.hexdigest()}
            data=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
            if len(data)>MAX_MANIFEST: raise ValueError('Слишком большой список файлов')
            z.writestr(MANIFEST,data)
        os.replace(tmp,destination)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return destination


def unpack(bundle, output_root):
    """Распаковка только в НОВУЮ папку проекта; при ошибке чистим частичные записи."""
    bundle=Path(bundle); output_root=Path(output_root)
    output_root.mkdir(parents=True,exist_ok=True)
    stage=None
    try:
        with zipfile.ZipFile(bundle) as z:
            entries=z.infolist(); names=[i.filename for i in entries]
            if len(names)>MAX_FILES+1 or len(set(n.casefold() for n in names))!=len(names):
                raise ValueError('Повтор имён или слишком много файлов')
            if MANIFEST not in names: raise ValueError('Это не файл .bolid нашей программы: нет manifest.json')
            if z.getinfo(MANIFEST).file_size>MAX_MANIFEST: raise ValueError('Слишком большой manifest.json')
            meta=json.loads(z.read(MANIFEST).decode('utf-8'))
            if meta.get('format')!=FORMAT or meta.get('version')!=VERSION:
                raise ValueError('Неподдерживаемая версия .bolid. Обновите программу.')
            files=meta.get('files',{})
            if not isinstance(files,dict) or not REQUIRED<=set(files) or set(files)!=set(names)-{MANIFEST}:
                raise ValueError('Неполный или несогласованный состав файла .bolid')
            total=0
            for i in entries:
                if i.filename!=MANIFEST and not safe_name(i.filename): raise ValueError('Недопустимый путь в архиве')
                if i.is_dir() or stat.S_ISLNK(i.external_attr>>16) or i.flag_bits&1:
                    raise ValueError('Каталоги, ссылки и шифрованные записи не допускаются')
                if i.file_size>MAX_FILE:raise ValueError('Превышен размер файла')
                if i.filename!=MANIFEST:total+=i.file_size
            if total>MAX_TOTAL:raise ValueError('Превышен суммарный размер')
            settings=clean_settings(meta.get('settings'))
            stage=Path(tempfile.mkdtemp(prefix='.opening_',dir=output_root))
            for name, expected in files.items():
                if not isinstance(expected,dict) or expected.get('size')!=z.getinfo(name).file_size or not re.fullmatch('[0-9a-f]{64}',str(expected.get('sha256',''))):
                    raise ValueError('Некорректный контрольный список')
                dest=stage/name;dest.parent.mkdir(parents=True,exist_ok=True)
                h=hashlib.sha256(); size=0
                with z.open(name) as src, open(dest,'xb') as f:
                    for chunk in iter(lambda:src.read(1024*1024),b''):
                        size+=len(chunk)
                        if size>expected['size']:raise ValueError('Файл больше заявленного')
                        h.update(chunk);f.write(chunk)
                if size!=expected['size'] or h.hexdigest()!=expected['sha256']:
                    raise ValueError('Файл повреждён: '+name)
            counts=validate_snapshot(stage)
            if counts!=meta.get('counts'):raise ValueError('Количество сотрудников/карт изменено')
            # Локальные пути с другого компьютера нельзя разбирать.
            (stage/'PORTABLE.txt').write_text('Only packaged photo cache may be read.\n',encoding='utf-8')
            from migration_data import enrich
            enrich(stage)
            (stage/'transfer_settings.json').write_text(json.dumps(settings,ensure_ascii=False),encoding='utf-8')
        final=output_root/('project_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        stage.rename(final);stage=None
        return final/'Проверка.csv'
    except (zipfile.BadZipFile,KeyError,TypeError,UnicodeDecodeError,json.JSONDecodeError) as ex:
        raise ValueError('Повреждённый или неподдерживаемый файл .bolid: '+str(ex)) from ex
    finally:
        if stage is not None:shutil.rmtree(stage,ignore_errors=True)
