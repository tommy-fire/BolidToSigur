"""Two-button workflow; full trial import does not claim verified W34 or rights.
The staff-only draft remains an internal regression/diagnostic option, not a UI setting.
"""
import datetime
import json
from pathlib import Path
from safe_w34 import snapshot, prepare, build, read_csv, write_csv, value
from transfer_bundle import pack, unpack

# Exact name hypotheses, never 'first date-like value'. All choices are reported.
START_NAMES={'start','validfrom','startdate','datestart','begindate','datebegin',
             'starttime','timestart','begintime','timebegin','datebeg','validsince'}
END_NAMES={'finish','validuntil','enddate','dateend','expiredate','expirationdate',
           'endtime','timeend','finishtime','timefinish','datefinish','datefin','validto'}


def unique_field(columns, aliases):
    found=[k for k in columns if k.casefold() in aliases]
    return found[0] if len(found)==1 else ''


def export_database(db, folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    source=snapshot(db['server'],db['db'],db.get('user'),db.get('password'),folder/'Служебные')
    prepare(source)
    filename=folder/('Болид_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.bolid')
    return pack(source,filename)


def convert_file(bundle, folder, staff_only=False):
    """New work copy only; no SQL and no inherited operator decisions."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    review=unpack(bundle,folder/'Служебные')
    review.unlink();prepare(review.parent)
    meta=json.loads((review.parent/'schema.json').read_text(encoding='utf-8'))
    cols=meta['tables']['pMark']['columns']
    start=unique_field(cols,START_NAMES);end=unique_field(cols,END_NAMES)
    result=build(review,end,start,'fields',candidate_draft=staff_only,trial_import=not staff_only)
    report=json.loads((result/'Отчёт.json').read_text(encoding='utf-8'))
    report['app_version']='3.4'
    report['automatic_date_suggestions']={'start':start,'end':end,'semantics_verified':False}
    report['note']+=' Имена полей дат выбраны автоматически, их смысл нужно сверить по карточке Болид.'
    marks=read_csv(review.parent/'pMark.csv')
    raw_by_id={value(m,'ID'):m for m in marks}
    structural={
        'app_version':'3.4',
        'tables':{name:{'columns':table.get('columns',{}),'rows':table.get('rows')} for name,table in meta['tables'].items()},
        'date_selection':report['automatic_date_suggestions'],
        'matching_start_columns':[k for k in cols if k.casefold() in START_NAMES],
        'matching_end_columns':[k for k in cols if k.casefold() in END_NAMES],
        'source_keys':len(marks),
        'missing_source_start_values':sum(not value(m,start).strip() for m in marks) if start else len(marks),
        'missing_source_end_values':sum(not value(m,end).strip() for m in marks) if end else len(marks),
    }
    # No row values, names, IDs, photos, passwords or card numbers in this shareable diagnostic.
    (result/'ДИАГНОСТИКА_СТРУКТУРЫ.json').write_text(json.dumps(structural,ensure_ascii=False,indent=2),encoding='utf-8')
    if not staff_only:
        cards=read_csv(result/'КАРТЫ_ПРОБНОГО_ИМПОРТА.csv')
        report['cards_without_start']=sum(not r.get('Начало действия пропуска') for r in cards)
        report['cards_without_end']=sum(not r.get('Срок действия') for r in cards)
        statuses=[]
        for r in cards:
            m=raw_by_id[r['SourceKeyID']]
            status_values={k:v for k,v in m.items() if any(t in k.casefold() for t in ('status','block','active','disable','delete','статус','блок'))}
            statuses.append({'ID ключа':r['SourceKeyID'],'ID владельца':r['SourcePersonID'],
                'Номер W34 — НЕ СВЕРЕН':r['FinalW34'],
                'Исходные поля статуса — смысл НЕ проверен':json.dumps(status_values,ensure_ascii=False) if status_values else 'Не распознаны; все поля в Данные_всех_ключей.csv',
                'Начало в XLS':r.get('Начало действия пропуска',''),
                'Окончание в XLS':r.get('Срок действия',''),
                'Замечание':'Блокировки НЕ перенесены. '+('Пустое начало; ' if not r.get('Начало действия пропуска') else '')+('Пустое окончание; ' if not r.get('Срок действия') else '')})
        write_csv(result/'ПРОВЕРИТЬ_СТАТУСЫ_И_СРОКИ.csv',statuses,['ID ключа','ID владельца','Номер W34 — НЕ СВЕРЕН','Исходные поля статуса — смысл НЕ проверен','Начало в XLS','Окончание в XLS','Замечание'])
    report['all_keys_exported']=not staff_only and report.get('trial_cards',0)==report['input_keys']
    report['production_ready']=False
    (result/'Отчёт.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    output=folder/('Для_Sigur_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    result.rename(output)
    stats=report.get('cards_file',{})
    if staff_only:
        text='КАДРОВЫЙ ЧЕРНОВИК: сотрудники без карт. Не назначать доступ. Номера только в отдельном CSV сверки.\n'
    else:
        text=f'''ПОЛНЫЙ ПРОБНЫЙ ИМПОРТ v3.4 — В ПУСТУЮ ИЗОЛИРОВАННУЮ БАЗУ SIGUR

Файл: {report['cards_filename'] if stats.get('file_created') else 'XLS не создан: нет однозначных сотрудников'}.
Сотрудников в XLS: {stats.get('people',0)}.
Карт в XLS: {report.get('trial_cards',0)} из {report['input_keys']} исходных записей.
Исключено записей ключей: {report['excluded']} — причины в Исключения.csv.
Неоднозначных сотрудников исключено: {report.get('excluded_staff',0)}.
Карт в XLS без начала: {report.get('cards_without_start',0)}; без окончания: {report.get('cards_without_end',0)}.
Фото: {stats.get('photos',0)}.

В отличие от v3.3 номера карт теперь действительно записываются в XLS.
Номера — расчётные кандидаты W34 (8 HEX-символов, включая ведущие нули),
гипотеза raw08-dallas01-low32. CRC проверена, но совпадение с физическим
считывателем НЕ проверено. В поле номера нет слов «НЕПОДТВЕРЖДЁН».
Пометка о пробном импорте находится в примечании сотрудника.

Сотрудники без карт и с исключёнными картами тоже включены в XLS.
Включены также неактивные/уволенные сотрудники и распознанные карты:
БЛОКИРОВКИ БОЛИД НЕ ПЕРЕНЕСЕНЫ. Права и режимы не назначены.
Отсутствие режимов в XLS НЕ блокирует доступ при ошибочном импорте
в существующую базу с унаследованными правами. Только изолированный тест!

КАК ИМПОРТИРОВАТЬ
1. Персонал → Импорт из таблицы MS Excel → выбрать указанный выше XLS.
2. Заново проверьте сопоставление: номера столбцов изменились с v3.3!
   ФИО → ФИО; Отдел → Отдел; Должность → Должность;
   Табельный номер → Табельный номер; Номер пропуска → Номер пропуска;
   Начало действия пропуска → Начало действия пропуска;
   Окончание действия пропуска → Окончание действия пропуска;
   Тип записи → Тип записи (значение «Сотрудник»), НЕ «Тип пропуска»;
   Имя файла фотографии → одноимённое поле; Примечание → Примечание.
3. «Тип пропуска» НЕ включать и НЕ сопоставлять: такого столбца в файле нет.
   По руководству Sigur без этого поля назначается тип «Карта».
   НЕ подставлять «W34», «Сотрудник», номер карты или пустую колонку.
4. Дата рождения/паспорт/прописка — дополнительные поля. Если они ещё
   не созданы, достаточно импортировать Примечание: там есть резервные
   строки «Дата рождения:», «Паспорт РФ:», «Прописка:» в нужном порядке.
   «Орион ID» — только для сверки; не назначать как ID или номер карты.
5. Для сотрудника с несколькими картами следующие строки без ФИО —
   продолжение его карточки, а не пустые сотрудники. Проверить все даты
   второй и последующих карт в установленной версии Sigur.

ДАТЫ
Поле начала: {start or 'НЕ НАЙДЕНО ОДНОЗНАЧНО'}.
Поле окончания: {end or 'НЕ НАЙДЕНО ОДНОЗНАЧНО'}.
Если значение распознано, дата И время сохраняются без округления.
При пустом/неоднозначном поле оставляем пустую ячейку, а не выдуманную дату.
Пустое окончание может дать бессрочную карту; пустое начало Sigur может
заменить временем импорта. Это НЕ подтверждение переноса сроков.
Если сроки не заполнились, пришлите ДИАГНОСТИКА_СТРУКТУРЫ.json: там только
названия/типы полей и количества, без значений персональных данных.
Недопустимые даты или начало не раньше окончания исключают эту карту.

ПЕРЕД ПЕРЕКЛЮЧЕНИЕМ
Сверить несколько реальных карт со считывателем, владельцев, начало/конец
(включая время), несколько карт на одного человека, фото, исходные блокировки.
Проверить количество сотрудников и карт по отчёту. Если исключения есть,
перенесены НЕ ВСЕ карты — причина указана для каждой исходной записи.
Успешный импорт Excel ещё не доказывает, что карта откроет турникет.
Рабочую систему не переключать и общий режим пока не назначать.
Позже: турникет — действующим сотрудникам с проверенными картами, 24/7;
комната охраны отдельно. Блокировки и индивидуальные сроки не отменять.

Если снова «неизвестный тип пропуска»: сделайте скрин сопоставления колонок
и полного сообщения с номером строки; укажите версию Sigur (Справка → О программе).
Пока причина прежней ошибки предположительна: исходный XLS не предоставлен.
Повторные импорты делайте в отдельной чистой тестовой базе, не поверх рабочей.
Фотографии должны оставаться рядом с XLS в папке Фотографии.
Все исходные ключи, включая исключённые, сохранены в Данные_всех_ключей.csv.
'''
    (output/'СНАЧАЛА_ПРОЧИТАТЬ.txt').write_text(text,encoding='utf-8-sig')
    return output,report
