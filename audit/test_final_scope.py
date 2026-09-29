import unittest, tempfile, json
from pathlib import Path
import test_safe
import migration_data as d
s=test_safe.s
class FinalScope(unittest.TestCase):
    def test_personal_notes_and_scope(self):
        warnings=[]
        extra,note=d.agreed_personal({'Notes':'Дата рождения: 02.01.1980\nПаспорт РФ: 0011 002233\nПрописка: Тест'},warnings,'1')
        self.assertEqual(extra,{'Дата рождения':'02.01.1980','Паспорт РФ':'0011 002233','Прописка':'Тест'})
        self.assertTrue(note.startswith('Дата рождения: 02.01.1980\nПаспорт РФ: 0011 002233\nПрописка: Тест'))
        self.assertTrue(warnings)
    def test_no_guess_and_conflict(self):
        for note in ['02.01.1980','Выдан 02.01.2020, до 03.01.2030','Дата рождения: 99.99.1980','Дата рождения: 01.01.2999']:
            warnings=[];extra,text=d.agreed_personal({'Notes':note},warnings,'1')
            self.assertNotIn('Дата рождения',extra);self.assertIn(note,text);self.assertTrue(warnings)
        extra,_=d.agreed_personal({'BirthDate':'1980-01-02','Notes':'Дата рождения: 03.01.1980'},[],'1')
        self.assertNotIn('Дата рождения',extra)
    def test_datetime_precision(self):
        self.assertEqual(d.normalize_access('2030-01-02T12:30:45'),'02.01.2030 12:30:45')
        for v in ['2030-01-02T12:30:45+03:00','2030-01-02T12:30:45.123','bad']:
            with self.assertRaises(ValueError):d.normalize_access(v)
    def test_start_end_continuation_excel(self):
        import xlrd
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=test_safe.Tests().fixture(root,2);marks=s.read_csv(root/'pMark.csv')
            for i,m in enumerate(marks):m.update(Start=f'2026-01-0{i+1}T12:11:13',Finish=f'2030-01-0{i+1}T19:22:47')
            s.write_csv(root/'pMark.csv',marks,list(marks[0]))
            rows=s.read_csv(path)
            for r in rows:r.update(Approve='ДА',ObservedW34=r['CandidateW34'])
            s.write_csv(path,rows,s.REVIEW)
            blocked=s.build(path,'Finish','Start');self.assertEqual(json.loads((blocked/'Отчёт.json').read_text())['accepted'],0)
            out=s.build(path,'Finish','Start',allow_multicard_dates=True);sh=xlrd.open_workbook(out/'ДИАГНОСТИКА_НЕ_ДЛЯ_РАБОТЫ.xls').sheet_by_index(0);headers=sh.row_values(0)
            for i in (1,2):
                vals=dict(zip(headers,sh.row_values(i)))
                self.assertEqual(vals['Начало действия пропуска'],f'0{i}.01.2026 12:11:13')
                self.assertEqual(vals['Окончание действия пропуска'],f'0{i}.01.2030 19:22:47')
                self.assertEqual(vals['Номер пропуска'],rows[i-1]['CandidateW34'])
                self.assertNotIn('Номер телефона',vals)
            self.assertEqual(sh.cell_value(2,0),'')
            out=s.build(path,'Finish','Start',personal_mode='notes',allow_multicard_dates=True)
            sh=xlrd.open_workbook(out/'ДИАГНОСТИКА_НЕ_ДЛЯ_РАБОТЫ.xls').sheet_by_index(0);headers=sh.row_values(0)
            self.assertNotIn('Дата рождения',headers)
            self.assertTrue(sh.cell_value(1,headers.index('Примечание')).startswith('Дата рождения:'))
            marks[0]['Start']='2031-01-01';s.write_csv(root/'pMark.csv',marks,list(marks[0]))
            out=s.build(path,'Finish','Start');self.assertEqual(json.loads((out/'Отчёт.json').read_text())['excluded'],1)
            with self.assertRaises(ValueError):s.build(path,'Finish','Finish')
