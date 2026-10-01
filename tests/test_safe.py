import unittest,sys,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ИНСТРУКЦИЯ'))
import safe_w34 as s

def raw(n):
    b=bytes([1])+n.to_bytes(4,'little')+b'\0\0';b+=bytes([s.crc8(b)])
    return '08'+b.hex().upper().replace('FE','FE02').replace('00','FE01')

class Tests(unittest.TestCase):
    def test_decode(self):
        for n in [0,1,0xFEFE0001,0xABCDEF12,0xFFFFFFFF]:
            a,c=s.decode(raw(n)); self.assertEqual(c,f'{n:08X}');self.assertEqual(s.decode(a,'abd'),(a,c))
    def test_reject(self):
        for h in ['ABC','08FE','08FE03','080102030405060708','00000000','08FE00','']:
            with self.assertRaises(ValueError):s.decode(h)
    def test_published_example(self):
        self.assertEqual(s.decode('0801B97A73FE0108FE012A')[0],'2A000800737AB901')
    def fixture(self,root,n=4):
        people=[{'ID':'1','Name':'Тест','FirstName':'Один','TabNumber':'T1'}]
        marks=[{'ID':str(i),'Owner':'1','CodeP':raw(0x12340000+i),'Status':'unknown'} for i in range(1,n+1)]
        s.write_csv(root/'pList.csv',people,list(people[0]));s.write_csv(root/'pMark.csv',marks,list(marks[0]))
        (root/'COMPLETE.txt').write_text('ok');(root/'schema.json').write_text(json.dumps({'tables':{'pMark':{'columns':{'CodeP':'varchar'}}}}))
        return s.prepare(root)
    def test_gates_and_xls(self):
        import xlrd
        with tempfile.TemporaryDirectory() as td:
            path=self.fixture(Path(td));rows=s.read_csv(path)
            o=s.build(path);self.assertFalse((o/'ТЕСТ_Импорт_Sigur.xls').exists())
            for i,r in enumerate(rows):
                r['Approve']='ДА';r['Profile']='reader-A'
                if i<3:r['ObservedW34']=r['CandidateW34']
            s.write_csv(path,rows,s.REVIEW);o=s.build(path)
            self.assertEqual(json.loads((o/'Отчёт.json').read_text())['accepted'],4)
            sh=xlrd.open_workbook(o/'ТЕСТ_Импорт_Sigur.xls').sheet_by_index(0)
            self.assertEqual(sh.nrows,5);self.assertEqual(sh.cell_value(1,3),'12340001');self.assertEqual(sh.cell_value(2,0),'')
            rows[0]['ObservedW34']='AAAAAAAA';s.write_csv(path,rows,s.REVIEW);o=s.build(path)
            self.assertFalse((o/'ТЕСТ_Импорт_Sigur.xls').exists())
    def test_overflow_and_identity(self):
        with tempfile.TemporaryDirectory() as td:
            path=self.fixture(Path(td),7);rows=s.read_csv(path)
            for r in rows:r['Approve']='ДА';r['ObservedW34']=r['CandidateW34']
            s.write_csv(path,rows,s.REVIEW);o=s.build(path)
            self.assertEqual(json.loads((o/'Отчёт.json').read_text())['excluded'],7)
            rows[0]['SourcePersonID']='2';s.write_csv(path,rows,s.REVIEW)
            with self.assertRaises(ValueError):s.build(path)
    def test_missing_keys(self):
        with tempfile.TemporaryDirectory() as td:
            path=self.fixture(Path(td));rows=s.read_csv(path);s.write_csv(path,rows[1:],s.REVIEW)
            with self.assertRaises(ValueError):s.build(path)
    def test_unknown_per_key(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=self.fixture(root,1)
            marks=s.read_csv(root/'pMark.csv');marks[0]['CodeP']='0800';s.write_csv(root/'pMark.csv',marks,list(marks[0]))
            rows=s.read_csv(path);rows[0].update(RawCodeP='0800',ObservedW34='A1234567',Approve='ДА');s.write_csv(path,rows,s.REVIEW)
            o=s.build(path);self.assertEqual(json.loads((o/'Отчёт.json').read_text())['accepted'],1)
if __name__=='__main__':unittest.main()

class CollisionTest(unittest.TestCase):
    def test_unapproved_other_owner_collision(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=Tests().fixture(root,1)
            marks=s.read_csv(root/'pMark.csv');marks.append({**marks[0],'ID':'2','Owner':'2'})
            s.write_csv(root/'pMark.csv',marks,list(marks[0]))
            people=s.read_csv(root/'pList.csv');people.append({**people[0],'ID':'2','Name':'Другой'})
            s.write_csv(root/'pList.csv',people,list(people[0]));path.unlink();path=s.prepare(root)
            rows=s.read_csv(path);rows[0]['Approve']='ДА';rows[0]['ObservedW34']=rows[0]['CandidateW34']
            s.write_csv(path,rows,s.REVIEW);out=s.build(path)
            self.assertEqual(json.loads((out/'Отчёт.json').read_text())['accepted'],0)
