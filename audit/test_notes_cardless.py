"""v3.5: birthday-only import notes and personnel independent of pass presence."""
import json
import tempfile
import unittest
from pathlib import Path
import xlrd
import test_simple
import test_trial
import safe_w34 as s
import migration_data as d


class NotesAndCardlessTests(unittest.TestCase):
    def test_notes_contain_only_birthday_all_xls_modes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            extra,note=d.agreed_personal({'BirthDate':'1980-01-02','PasportN':'SECRET-PASSPORT','Address':'SECRET-ADDRESS','Notes':'SECRET-SOURCE-NOTE'},[],'1')
            person={'fio':'Тест','dept':'Отдел','tab':'001','post':'Должность','photo':'','extra':extra,'note':note}
            for i,opts in enumerate([{}, {'personal_mode':'notes'}, {'draft_marker':True}, {'trial_marker':True}, {'experimental':True}]):
                path=root/f'{i}.xls'
                d.export_xls(path,{'1':person},root,**opts)
                sh=xlrd.open_workbook(path).sheet_by_index(0);row=dict(zip(sh.row_values(0),sh.row_values(1)))
                self.assertEqual(row['Примечание'],'Дата рождения: 02.01.1980')
                if opts.get('personal_mode')!='notes':
                    self.assertEqual(row['Паспорт РФ'],'SECRET-PASSPORT');self.assertEqual(row['Прописка'],'SECRET-ADDRESS')

    def test_absent_invalid_conflicting_birthdate_makes_empty_note(self):
        for src in [
            {'PasportN':'SECRET','Address':'PRIVATE','Notes':'Do not copy this'},
            {'BirthDate':'not a date'},
            {'BirthDate':'2999-01-01'},
            {'BirthDate':'1980-01-01','Notes':'Дата рождения: 02.01.1980'},
            {'Notes':'Дата рождения: 01.01.1980\nДата рождения: 02.01.1980'},
            {'BirthDate':'SECRET\nПаспорт РФ: PRIVATE'},
        ]:
            with self.subTest(src=src):
                extra,note=d.agreed_personal(src,[],'1')
                self.assertEqual(d.birthdate_note({'extra':extra,'note':note}),'')

    def test_birthday_from_source_note_without_copying_other_lines(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,_=test_simple.SimpleTests().setup_bundle(root)
            people=s.read_csv(src/'pList.csv');people[0]['Notes']='Дата рождения: 02.01.1980\nПаспорт РФ: SECRET\nПрописка: PRIVATE\nOLD SERVICE TEXT'
            s.write_csv(src/'pList.csv',people,list(people[0]))
            _,report,rows=test_trial.TrialTests().convert(src,root)
            self.assertEqual(rows[0]['Примечание'],'Дата рождения: 02.01.1980')
            self.assertEqual(report['cards_file']['people_without_cards'],0)
            self.assertIn('OLD SERVICE TEXT',(src/'pList.csv').read_text())

    def test_only_cardless_staff_still_create_full_xls(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,path=test_simple.SimpleTests().setup_bundle(root)
            marks=s.read_csv(src/'pMark.csv');s.write_csv(src/'pMark.csv',[],list(marks[0]))
            people=s.read_csv(src/'pList.csv');people[0]['BirthDate']='1980-01-02'
            people.append({**people[0],'ID':'2','Name':'Второй','TabNumber':'002','BirthDate':''})
            s.write_csv(src/'pList.csv',people,list(people[0]));path.unlink();s.prepare(src)
            _,report,rows=test_trial.TrialTests().convert(src,root)
            self.assertEqual(report['input_keys'],0);self.assertEqual(report['trial_cards'],0)
            self.assertEqual(report['cards_file']['people'],2);self.assertEqual(report['cards_file']['people_without_cards'],2)
            self.assertEqual({r['Орион ID'] for r in rows},{'1','2'})
            for r in rows:
                self.assertEqual(r['Тип записи'],'Сотрудник');self.assertTrue(r['ФИО'])
                for col in ['Номер пропуска','Начало действия пропуска','Окончание действия пропуска']:self.assertEqual(r[col],'')
            self.assertEqual(rows[0]['Примечание'],'Дата рождения: 02.01.1980');self.assertEqual(rows[1]['Примечание'],'')

    def test_mixed_staff_cardless_and_continuation_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src,_=test_simple.SimpleTests().setup_bundle(root,n=2)
            people=s.read_csv(src/'pList.csv');people[0]['BirthDate']='1980-01-02'
            people.append({**people[0],'ID':'2','Name':'Без ключа','TabNumber':'002'})
            s.write_csv(src/'pList.csv',people,list(people[0]))
            _,report,rows=test_trial.TrialTests().convert(src,root)
            self.assertEqual(report['cards_file']['people'],2);self.assertEqual(report['trial_cards'],2)
            self.assertEqual(report['cards_file']['people_without_cards'],1)
            self.assertEqual([r['Примечание'] for r in rows],['Дата рождения: 02.01.1980','','Дата рождения: 02.01.1980'])
            self.assertEqual(rows[1]['ФИО'],'');self.assertTrue(rows[1]['Номер пропуска'])
            self.assertTrue(rows[2]['ФИО']);self.assertEqual(rows[2]['Номер пропуска'],'')

if __name__=='__main__':unittest.main()
