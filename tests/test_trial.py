"""Полный пробный импорт: проверяется содержимое XLS, а не живое поведение Sigur и считывателя."""
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xlrd
from PIL import Image
import test_simple
import test_safe
import safe_w34 as s
import transfer_bundle as b
import simple_flow as flow


class TrialTests(unittest.TestCase):
    def fixture(self,root,n=1,dates=True):
        return test_simple.SimpleTests().setup_bundle(root,n,dates)

    def convert(self,src,root):
        package=b.pack(src,root/'data.bolid')
        before=hashlib.sha256(package.read_bytes()).hexdigest()
        with patch.object(s,'load_exporter',side_effect=AssertionError('No SQL at step 2')):
            out,report=flow.convert_file(package,root/'app')
        self.assertEqual(hashlib.sha256(package.read_bytes()).hexdigest(),before)
        self.assertTrue(report['trial_import']);self.assertFalse(report['hardware_verified'])
        self.assertFalse(report['production_ready']);self.assertFalse(report['access_rights_assigned'])
        self.assertFalse(report['source_statuses_verified']);self.assertNotIn('accepted',report)
        self.assertEqual(report['trial_cards']+report['excluded'],report['input_keys'])
        self.assertFalse((out/'Принятые.csv').exists())
        self.assertEqual(out.parent,root/'app')
        if not report['cards_file']['file_created']:return out,report,[]
        sh=xlrd.open_workbook(out/report['cards_filename']).sheet_by_index(0)
        headers=sh.row_values(0)
        self.assertNotIn('Тип пропуска',headers)  # absent means Card per manual, not blank type
        self.assertNotIn('Номер телефона',headers);self.assertNotIn('Email',headers)
        for i in range(1,sh.nrows):
            for cell in sh.row(i):
                if cell.value:self.assertEqual(cell.ctype,xlrd.XL_CELL_TEXT)
        rows=[dict(zip(headers,sh.row_values(i))) for i in range(1,sh.nrows)]
        self.assertEqual(sum(bool(r['Номер пропуска']) for r in rows),report['trial_cards'])
        self.assertEqual(sum(bool(r['ФИО']) for r in rows),report['cards_file']['people'])
        return out,report,rows

    def test_full_person_photo_card_dates_without_fake_approval(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,path=self.fixture(root)
            marks=s.read_csv(src/'pMark.csv');marks[0]['CodeP']=test_safe.raw(0x123)
            s.write_csv(src/'pMark.csv',marks,list(marks[0]));path.unlink();s.prepare(src)
            image=io.BytesIO();Image.new('RGB',(20,20),'red').save(image,'PNG')
            people=s.read_csv(src/'pList.csv');people[0].update(Company='10',Section='20',Post='30',Picture=image.getvalue().hex(),BirthDate='1980-01-02',PasportN='000011',Address='Тестовый адрес',Phone='EXCLUDED-PHONE',Email='EXCLUDED-EMAIL')
            people.append({**people[0],'ID':'2','Name':'Без карты','TabNumber':'002'})
            s.write_csv(src/'pList.csv',people,list(people[0]))
            for table,id,name in [('PCompany','10','Компания'),('PDivision','20','Отдел'),('PPost','30','Должность')]:
                s.write_csv(src/(table+'.csv'),[{'ID':id,'Name':name}],['ID','Name'])
            out,report,rows=self.convert(src,root)
            self.assertEqual(report['trial_cards'],1);self.assertEqual(len(rows),2)
            first=rows[0]
            self.assertEqual(first['Номер пропуска'],'00000123');self.assertEqual(first['Тип записи'],'Сотрудник')
            self.assertEqual(first['Начало действия пропуска'],'02.01.2020 12:13:14')
            self.assertEqual(first['Окончание действия пропуска'],'02.01.2030 15:16:17')
            self.assertEqual(first['Отдел'],'Компания, Отдел');self.assertEqual(first['Должность'],'Должность')
            self.assertEqual(first['Паспорт РФ'],'000011');self.assertEqual(first['Дата рождения'],'02.01.1980')
            self.assertEqual(first['Примечание'],'Дата рождения: 02.01.1980')
            self.assertTrue((out/first['Имя файла фотографии'].replace('\\','/')).exists())
            self.assertEqual(rows[1]['Номер пропуска'],'')
            work=next((root/'app'/'Служебные').glob('project_*'));review=s.read_csv(work/'Проверка.csv')
            self.assertEqual(review[0]['Approve'],'');self.assertEqual(review[0]['ObservedW34'],'')
            self.assertEqual(review[0]['Поле срока'],'Finish')

    def test_missing_dates_keep_card_and_report_unknown_not_invented(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,_=self.fixture(root,dates=False)
            out,report,rows=self.convert(src,root)
            self.assertEqual(report['trial_cards'],1)
            self.assertEqual(rows[0]['Начало действия пропуска'],'');self.assertEqual(rows[0]['Окончание действия пропуска'],'')
            self.assertEqual(report['cards_without_end'],1);self.assertEqual(report['cards_without_start'],1)
            diag=json.loads((out/'ДИАГНОСТИКА_СТРУКТУРЫ.json').read_text())
            self.assertEqual(diag['date_selection']['start'],'')
            text=(out/'ДИАГНОСТИКА_СТРУКТУРЫ.json').read_text()
            for personal in ['Тест Один',test_safe.raw(0x12340001),'12340001','unknown']:self.assertNotIn(personal,text)

    def test_multiple_cards_have_own_dates_and_blank_identity_on_continuation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,_=self.fixture(root,n=5)
            marks=s.read_csv(src/'pMark.csv')
            for i,m in enumerate(marks,1):m.update(Start=f'2020-02-0{i}T12:13:14',Finish=f'2030-02-0{i}T15:16:17')
            s.write_csv(src/'pMark.csv',marks,list(marks[0]))
            _,report,rows=self.convert(src,root)
            self.assertEqual(report['trial_cards'],5);self.assertEqual(report['cards_file']['people'],1)
            for i,r in enumerate(rows,1):
                self.assertEqual(r['Начало действия пропуска'],f'0{i}.02.2020 12:13:14')
                self.assertEqual(r['Окончание действия пропуска'],f'0{i}.02.2030 15:16:17')
                if i>1:self.assertEqual({k for k,v in r.items() if v},{'Номер пропуска','Начало действия пропуска','Окончание действия пропуска'})

    def test_unknown_code_keeps_person_without_wrong_number(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,path=self.fixture(root)
            marks=s.read_csv(src/'pMark.csv');marks[0]['CodeP']='0800';s.write_csv(src/'pMark.csv',marks,list(marks[0]))
            path.unlink();s.prepare(src)
            out,report,rows=self.convert(src,root)
            self.assertEqual(report['trial_cards'],0);self.assertEqual(report['excluded'],1)
            self.assertEqual(rows[0]['Номер пропуска'],'');self.assertTrue(s.read_csv(out/'Исключения.csv')[0]['Reason'])
            self.assertEqual(s.read_csv(out/'Данные_всех_ключей.csv')[0]['CodeP'],'0800')

    def test_bad_dates_exclude_card_not_employee(self):
        for bad in ['not a date','2031-01-01','2020-01-02T12:13:14.123']:
            with self.subTest(bad=bad),tempfile.TemporaryDirectory() as td:
                root=Path(td);src,_=self.fixture(root)
                marks=s.read_csv(src/'pMark.csv');marks[0]['Start']=bad;s.write_csv(src/'pMark.csv',marks,list(marks[0]))
                _,report,rows=self.convert(src,root)
                self.assertEqual(report['trial_cards'],0);self.assertEqual(len(rows),1)

    def test_collisions_and_overflow_not_forced_into_xls(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,path=self.fixture(root)
            people=s.read_csv(src/'pList.csv');people.append({**people[0],'ID':'2','Name':'Другой','TabNumber':'002'})
            s.write_csv(src/'pList.csv',people,list(people[0]))
            marks=s.read_csv(src/'pMark.csv');marks.append({**marks[0],'ID':'2','Owner':'2'});s.write_csv(src/'pMark.csv',marks,list(marks[0]));path.unlink();s.prepare(src)
            _,report,rows=self.convert(src,root)
            self.assertEqual(report['trial_cards'],0);self.assertEqual(report['excluded'],2);self.assertEqual(len(rows),2)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,_=self.fixture(root,n=6)
            _,report,rows=self.convert(src,root)
            self.assertEqual(report['trial_cards'],0);self.assertEqual(report['excluded'],6);self.assertEqual(len(rows),1)

    def test_source_status_is_not_claimed_migrated(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,_=self.fixture(root)
            marks=s.read_csv(src/'pMark.csv');marks[0]['Status']='blocked';s.write_csv(src/'pMark.csv',marks,list(marks[0]))
            out,report,rows=self.convert(src,root)
            self.assertEqual(report['trial_cards'],1) # явный изолированный полный пробный импорт, а не миграция только активных
            self.assertFalse(report['source_statuses_verified']);self.assertNotIn('Режимы',rows[0])
            self.assertIn('blocked',(out/'ПРОВЕРИТЬ_СТАТУСЫ_И_СРОКИ.csv').read_text())
            self.assertIn('БЛОКИРОВКИ БОЛИД НЕ ПЕРЕНЕСЕНЫ',(out/'СНАЧАЛА_ПРОЧИТАТЬ.txt').read_text())

    def test_carried_approvals_and_dates_not_inherited(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,path=self.fixture(root)
            review=s.read_csv(path);review[0].update(Approve='ДА',ObservedW34='DEADBEEF',Profile='Fake',**{'Срок действия':'01.01.2099','Начало действия пропуска':'01.01.1900'})
            s.write_csv(path,review,s.REVIEW)
            out,report,rows=self.convert(src,root)
            self.assertEqual(rows[0]['Номер пропуска'],'12340001');self.assertEqual(report['calibrated_profiles'],[])
            self.assertEqual(rows[0]['Окончание действия пропуска'],'02.01.2030 15:16:17')
            self.assertNotIn('DEADBEEF',(out/'КАРТЫ_ПРОБНОГО_ИМПОРТА.csv').read_text())

    def test_alias_ambiguity_reported_and_end_still_exported(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,_=self.fixture(root)
            marks=s.read_csv(src/'pMark.csv');marks[0]['DateStart']='2019-01-01';s.write_csv(src/'pMark.csv',marks,list(marks[0]))
            meta=json.loads((src/'schema.json').read_text());meta['tables']['pMark']['columns']['DateStart']='datetime';(src/'schema.json').write_text(json.dumps(meta))
            out,report,rows=self.convert(src,root)
            self.assertEqual(rows[0]['Начало действия пропуска'],'');self.assertEqual(rows[0]['Окончание действия пропуска'],'02.01.2030 15:16:17')
            self.assertEqual(report['trial_cards'],1)
            self.assertEqual(json.loads((out/'ДИАГНОСТИКА_СТРУКТУРЫ.json').read_text())['matching_start_columns'],['Start','DateStart'])

    def test_ambiguous_staff_and_unsupported_sql_type_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,_=self.fixture(root)
            people=s.read_csv(src/'pList.csv');people.append({**people[0],'ID':'2'});s.write_csv(src/'pList.csv',people,list(people[0]))
            _,report,rows=self.convert(src,root)
            self.assertEqual(report['excluded_staff'],2);self.assertFalse(report['cards_file']['file_created'])
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,_=self.fixture(root)
            meta=json.loads((src/'schema.json').read_text());meta['tables']['pMark']['columns']['CodeP']='int';(src/'schema.json').write_text(json.dumps(meta))
            _,report,rows=self.convert(src,root)
            self.assertEqual(report['trial_cards'],0);self.assertEqual(len(rows),1)

if __name__=='__main__':unittest.main()
