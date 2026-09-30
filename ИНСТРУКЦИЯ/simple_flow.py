"""No-option workflow. Automatic output is a marked TEST draft, never an approval.
The strict calibrated backend remains available to verification tools/tests.
"""
import datetime
import json
from pathlib import Path
from safe_w34 import snapshot, prepare, build
from transfer_bundle import pack, unpack

START_NAMES={'start','validfrom','startdate','datestart','begindate','datebegin'}
END_NAMES={'finish','validuntil','enddate','dateend','expiredate','expirationdate'}


def unique_field(columns, aliases):
    found=[k for k in columns if k.casefold() in aliases]
    return found[0] if len(found)==1 else ''


def export_database(db, folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    source=snapshot(db['server'],db['db'],db.get('user'),db.get('password'),folder/'Служебные')
    prepare(source)
    filename=folder/('Болид_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.bolid')
    return pack(source,filename)


def convert_file(bundle, folder):
    """Ignore carried operator decisions: no approvals are created or inherited."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    review=unpack(bundle,folder/'Служебные')
    # Recreate only the new work copy. The input .bolid is untouched.
    review.unlink();prepare(review.parent)
    meta=json.loads((review.parent/'schema.json').read_text(encoding='utf-8'))
    cols=meta['tables']['pMark']['columns']
    start=unique_field(cols,START_NAMES);end=unique_field(cols,END_NAMES)
    result=build(review,end,start,'fields',candidate_draft=True)
    report=json.loads((result/'Отчёт.json').read_text(encoding='utf-8'))
    report['automatic_date_suggestions']={'start':start,'end':end,'semantics_verified':False}
    report['note']+=' Даты выбраны по точным именам полей, их смысл нужно сверить по первой выгрузке.'
    (result/'Отчёт.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    output=folder/('Для_Sigur_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    result.rename(output)
    counts=report.get('cards_file',{})
    text=f'''РЕЗУЛЬТАТ АВТОМАТИЧЕСКОЙ ПОДГОТОВКИ — ТОЛЬКО ПРОВЕРКА

Сотрудников в XLS: {counts.get('people',0)}.
Кандидатов в отдельном CSV сверки: {report.get('draft_candidates',0)}.
Записей ключей без переноса номера: {report.get('excluded',0)}.
Неоднозначных сотрудников отдельно: {report.get('excluded_staff',0)}.

Файл: {report.get('cards_filename','') if counts.get('file_created') else 'XLS не создан: нет однозначных сотрудников'}.
XLS — сотрудники БЕЗ номеров карт. Неподтверждённые номера
в отдельном CSV КАРТЫ_ТОЛЬКО_СВЕРКА_НЕ_ИМПОРТ; НЕ импортируйте его как пропуска!
Открывайте XLS только в ПУСТОЙ ИЗОЛИРОВАННОЙ ТЕСТОВОЙ базе Sigur.
Всем кадровым записям в файле добавлен тестовый родительский отдел.
НЕ назначайте ему права. Название отдела само по себе НЕ блокирует доступ!
Номера карт НЕ сверены со считывателем; статусы Болид НЕ интерпретированы.
Кадровые записи не отфильтрованы по активности: могут включать уволенных
и заблокированных сотрудников. Это не файл для
переключения работающего турникета. Блокировки автоматически не перенесены.

Предположенные поля дат: начало={start or 'не найдено однозначно'}, окончание={end or 'не найдено однозначно'}.
Смысл этих полей не подтверждён. Пустые/непонятные даты, ошибки кодов,
коллизии и неоднозначные владельцы не исправляются догадками.
Сотрудники сохраняются без номера исключённой карты. Смотрите Исключения.csv.
Все исходные записи ключей сохранены в Данные_всех_ключей.csv.

Дата рождения/паспорт/прописка: отдельные поля, плюс резервное примечание
при проблемах разбора. Смотрите Предупреждения_данных.csv. Фотографии держите
рядом с XLS. В Sigur: Персонал → Импорт из Excel → сопоставить колонки.

Перед рабочим переносом нужны реальные контрольные номера карт и проверка
обеих дат, владельца, блокировок и прав. Для сотрудников согласован Турникет
24/7 (вход/выход), комнату охраны не включать. Права здесь НЕ назначены. Пустые даты в кадровом XLS не являются запретом.
Повторный импорт в рабочую базу не проверен: возможны дубли. «Орион ID»
оставлен для сверки, но он не назначает ID сотрудника в Sigur.
'''
    (output/'СНАЧАЛА_ПРОЧИТАТЬ.txt').write_text(text,encoding='utf-8-sig')
    return output,report
