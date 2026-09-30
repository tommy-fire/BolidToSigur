import unittest, tempfile, json, hashlib
from pathlib import Path
from unittest.mock import patch
import test_bundle
import test_safe
import safe_w34 as s
import transfer_bundle as b
import simple_flow as simple

class SimpleTests(unittest.TestCase):
    def setup_bundle(self,root,n=1,dates=True):
        src=root/'source';src.mkdir();path=test_bundle.fixture(src,n)
        if dates:
            marks=s.read_csv(src/'pMark.csv')
            for m in marks:m.update(Start='2020-01-02T12:13:14',Finish='2030-01-02T15:16:17')
            s.write_csv(src/'pMark.csv',marks,list(marks[0]))
            meta=json.loads((src/'schema.json').read_text());meta['tables']['pMark']['columns'].update(Start='datetime',Finish='datetime')
            (src/'schema.json').write_text(json.dumps(meta))
        return src,path

    def assert_no_passes(self,out,report):
        import xlrd
        sh=xlrd.open_workbook(out/report['cards_filename']).sheet_by_index(0)
        headers=sh.row_values(0)
        for i in range(1,sh.nrows):
            r=dict(zip(headers,sh.row_values(i)))
            for field in ['Номер пропуска','Тип пропуска','Начало действия пропуска','Окончание действия пропуска']:self.assertEqual(r[field],'')
            self.assertIn('НЕ НАЗНАЧАТЬ ДОСТУП',r['Отдел']);self.assertIn('НЕ ПРОВЕРЕНЫ',r['Примечание'])
        self.assertNotIn('accepted',report);self.assertFalse(report['hardware_verified']);self.assertFalse(report['access_rights_assigned'])
        self.assertFalse((out/'Принятые.csv').exists())
        return sh

    def test_two_steps_no_sql_no_fake_approvals(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,path=self.setup_bundle(root)
            marks=s.read_csv(src/'pMark.csv');marks[0]['CodeP']=test_safe.raw(0x00000123);s.write_csv(src/'pMark.csv',marks,list(marks[0]))
            path.unlink();s.prepare(src)
            package=b.pack(src,root/'data.bolid');before=hashlib.sha256(package.read_bytes()).hexdigest()
            with patch.object(s,'load_exporter',side_effect=AssertionError('No SQL')):
                out,report=simple.convert_file(package,root/'app')
            self.assert_no_passes(out,report);self.assertEqual(report['draft_candidates'],1)
            self.assertEqual(hashlib.sha256(package.read_bytes()).hexdigest(),before)
            diagnostic=s.read_csv(out/'КАРТЫ_ТОЛЬКО_СВЕРКА_НЕ_ИМПОРТ.csv')
            self.assertEqual(diagnostic[0]['НЕПОДТВЕРЖДЁННЫЙ кандидат W34'],'НЕПОДТВЕРЖДЁН:00000123')
            work=next((root/'app'/'Служебные').glob('project_*'));r=s.read_csv(work/'Проверка.csv')[0]
            self.assertEqual(r['Approve'],'');self.assertEqual(r['ObservedW34'],'')
            self.assertTrue((out/'СНАЧАЛА_ПРОЧИТАТЬ.txt').exists())

    def test_no_dates_unknown_codes_and_source_status_not_activated(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,path=self.setup_bundle(root,dates=False)
            marks=s.read_csv(src/'pMark.csv');marks[0].update(CodeP='0800',Status='blocked');s.write_csv(src/'pMark.csv',marks,list(marks[0]));path.unlink();s.prepare(src)
            package=b.pack(src,root/'data.bolid');out,report=simple.convert_file(package,root/'app')
            sh=self.assert_no_passes(out,report);self.assertEqual(sh.nrows,2)
            self.assertEqual(report['draft_candidates'],0);self.assertEqual(report['excluded'],1)
            self.assertFalse(report['source_statuses_verified'])

    def test_ambiguous_staff_does_not_crash_or_export_wrong_owner(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,path=self.setup_bundle(root)
            people=s.read_csv(src/'pList.csv');people.append({**people[0],'ID':'2'});s.write_csv(src/'pList.csv',people,list(people[0]))
            package=b.pack(src,root/'data.bolid');out,report=simple.convert_file(package,root/'app')
            self.assertEqual(report['excluded_staff'],2);self.assertEqual(report['draft_candidates'],0)
            self.assertFalse(report['cards_file']['file_created']);self.assertFalse(list(out.glob('*.xls')))

    def test_carried_approvals_are_not_used_for_draft(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,path=self.setup_bundle(root)
            rows=s.read_csv(path);rows[0].update(Approve='ДА',ObservedW34='DEADBEEF');s.write_csv(path,rows,s.REVIEW)
            package=b.pack(src,root/'data.bolid');out,report=simple.convert_file(package,root/'app');self.assert_no_passes(out,report)
            self.assertEqual(report['calibrated_profiles'],[])
            self.assertNotIn('DEADBEEF',(out/'КАРТЫ_ТОЛЬКО_СВЕРКА_НЕ_ИМПОРТ.csv').read_text())

    def test_date_ambiguity_and_multiple_cards_retained_without_passes(self):
        self.assertEqual(simple.unique_field(['Start','ValidFrom'],simple.START_NAMES),'')
        self.assertEqual(simple.unique_field(['CreatedAt'],simple.START_NAMES),'')
        self.assertEqual(simple.unique_field(['sTaRt'],simple.START_NAMES),'sTaRt')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,path=self.setup_bundle(root,n=2)
            out,report=simple.convert_file(b.pack(src,root/'data.bolid'),root/'app')
            self.assert_no_passes(out,report);self.assertEqual(report['excluded'],2)
            self.assertEqual(len(s.read_csv(out/'Данные_всех_ключей.csv')),2)

    def test_export_saves_next_to_app(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,path=self.setup_bundle(root);path.unlink()
            with patch.object(simple,'snapshot',return_value=src):
                package=simple.export_database({'server':'mock','db':'mock'},root/'app')
            self.assertEqual(package.parent,root/'app');self.assertEqual(package.suffix,'.bolid')
            self.assertTrue(package.exists())
