import unittest,sys,tempfile,json,io
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ИНСТРУКЦИЯ'))
import safe_w34 as s
import migration_data as d
import test_safe

class DataTests(unittest.TestCase):
    def test_enrichment_photos_and_excel(self):
        from PIL import Image
        import xlrd
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=test_safe.Tests().fixture(root,1)
            b=io.BytesIO();Image.new('RGB',(30,30),'red').save(b,'PNG')
            people=s.read_csv(root/'pList.csv')
            people[0].update(Picture=b.getvalue().hex(),Company='12',Section='34',Post='56',BirthDate='1980-01-02',Phone='000123',Address='Тестовый адрес',PasportN='00000123')
            people.append({**people[0],'ID':'2','Name':'Без ключа','TabNumber':'002'})
            s.write_csv(root/'pList.csv',people,list(people[0]))
            for table,ident,name in [('PCompany','12','Компания'),('PDivision','34','Отдел'),('PPost','56','Должность')]:
                s.write_csv(root/(table+'.csv'),[{'ID':ident,'Name':name}],['ID','Name'])
            path.unlink();s.prepare(root)
            rows=s.read_csv(path);self.assertEqual(rows[0]['Отдел'],'Компания, Отдел');self.assertEqual(rows[0]['Должность'],'Должность')
            rows[0]['Approve']='ДА';rows[0]['ObservedW34']=rows[0]['CandidateW34'];s.write_csv(path,rows,s.REVIEW)
            out=s.build(path);report=json.loads((out/'Отчёт.json').read_text())
            self.assertEqual(report['staff_file']['people'],2);self.assertEqual(report['cards_file']['people'],1)
            self.assertEqual(len(list((out/'Фотографии').glob('*.jpg'))),2)
            sh=xlrd.open_workbook(out/'ТЕСТ_Импорт_Sigur.xls').sheet_by_index(0);headers=sh.row_values(0);vals=dict(zip(headers,sh.row_values(1)))
            self.assertNotIn('Номер телефона',vals);self.assertEqual(vals['Паспорт РФ'],'00000123');self.assertEqual(vals['Дата рождения'],'02.01.1980');self.assertEqual(vals['Примечание'],'Дата рождения: 02.01.1980');self.assertEqual(vals['Прописка'],'Тестовый адрес')
    def test_large_csv_field(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'big.csv';s.write_csv(path,[{'x':'F'*500000}],['x']);self.assertEqual(len(s.read_csv(path)[0]['x']),500000)
    def test_discovery_auth_and_close(self):
        e=Mock();e.collect_servers.return_value=['localhost'];conn=Mock()
        e.connect.side_effect=[RuntimeError('login failed'),conn];e.find_orion_dbs.return_value=[('Orion',23)]
        with patch.object(s,'load_exporter',return_value=e):res=s.discover('sqluser','pass')
        self.assertEqual(res[0]['user'],None);self.assertEqual(res[0]['db'],'Orion');conn.close.assert_called_once()
    def test_expiry_requires_explicit_field(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=test_safe.Tests().fixture(root,1);marks=s.read_csv(root/'pMark.csv');marks[0]['Finish']='2030-01-02T00:00:00'
            s.write_csv(root/'pMark.csv',marks,list(marks[0]));rows=s.read_csv(path);rows[0]['Approve']='ДА';rows[0]['ObservedW34']=rows[0]['CandidateW34'];s.write_csv(path,rows,s.REVIEW)
            out=s.build(path,'Finish');self.assertEqual(s.read_csv(out/'Принятые.csv')[0]['Срок действия'],'02.01.2030 00:00:00')
            marks[0]['Finish']='2030-01-02T12:30:00';s.write_csv(root/'pMark.csv',marks,list(marks[0]));out=s.build(path,'Finish')
            self.assertEqual(s.read_csv(out/'Принятые.csv')[0]['Срок действия'],'02.01.2030 12:30:00')
    def test_photo_error_does_not_abort(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);test_safe.Tests().fixture(root,1);people=s.read_csv(root/'pList.csv');people[0]['Picture']='BADPHOTO';s.write_csv(root/'pList.csv',people,list(people[0]))
            people=d.enrich(root);self.assertEqual(people['1']['photo'],'');self.assertEqual(len(s.read_csv(root/'Предупреждения_данных.csv')),1)

class CoverageTest(unittest.TestCase):
    def test_unseen_upper_bytes_are_not_auto_migrated(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=test_safe.Tests().fixture(root,4)
            marks=s.read_csv(root/'pMark.csv')
            b=b'\x01'+(0x12340004).to_bytes(4,'little')+b'\x12\x34';b+=bytes([s.crc8(b)])
            marks[3]['CodeP']='08'+b.hex().upper().replace('FE','FE02').replace('00','FE01')
            s.write_csv(root/'pMark.csv',marks,list(marks[0]));path.unlink();s.prepare(root)
            rows=s.read_csv(path)
            for i,r in enumerate(rows):
                r['Approve']='ДА';r['Profile']='same'
                if i<3:r['ObservedW34']=r['CandidateW34']
            s.write_csv(path,rows,s.REVIEW);out=s.build(path)
            report=json.loads((out/'Отчёт.json').read_text());self.assertEqual(report['accepted'],3);self.assertEqual(report['excluded'],1)

class SnapshotTest(unittest.TestCase):
    def test_readonly_snapshot_keeps_orphans_and_long_codes(self):
        class Cursor:
            def execute(self,sql,*params):
                self.sql=sql
                statements.append(sql)
                if 'INFORMATION_SCHEMA.TABLES' in sql:
                    self.rows=[('dbo',params[0])] if params[0] in ('pList','pMark') else []
                elif 'INFORMATION_SCHEMA.COLUMNS' in sql:
                    self.rows=[('ID','int'),('Name','varchar')] if params[1]=='pList' else [('ID','int'),('Owner','int'),('CodeP','varchar')]
                elif 'FROM [dbo].[pList]' in sql:self.rows=[(1,'Тест')]
                elif 'FROM [dbo].[pMark]' in sql:self.rows=[(5,999,b'x'*300)]
                else:raise AssertionError(sql)
                return self
            def fetchall(self):return self.rows
            def __iter__(self):return iter(self.rows)
        statements=[];e=Mock();e.qi=lambda x:'['+x+']';conn=Mock();conn.cursor.return_value=Cursor();e.connect.return_value=conn
        with tempfile.TemporaryDirectory() as td,patch.object(s,'load_exporter',return_value=e):
            folder=s.snapshot('server','db','u','p',td)
            self.assertTrue((folder/'COMPLETE.txt').exists());m=s.read_csv(folder/'pMark.csv')[0]
            self.assertEqual(m['Owner'],'999');self.assertEqual(len(m['CodeP']),600)
            self.assertTrue(all(sql.startswith('SELECT') for sql in statements));self.assertTrue(any('varbinary(max)' in sql for sql in statements))
            conn.close.assert_called_once()

class CalibrationTest(unittest.TestCase):
    def test_symmetric_samples_not_discriminating(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=test_safe.Tests().fixture(root,3);marks=s.read_csv(root/'pMark.csv')
            for m,n in zip(marks,[0x12212112,0x23323223,0x34434334]):m['CodeP']=test_safe.raw(n)
            s.write_csv(root/'pMark.csv',marks,list(marks[0]));path.unlink();s.prepare(root);rows=s.read_csv(path)
            for r in rows:r.update(Approve='ДА',Profile='symmetric',ObservedW34=r['CandidateW34'])
            s.write_csv(path,rows,s.REVIEW);out=s.build(path);report=json.loads((out/'Отчёт.json').read_text())
            # Отдельные замеры при этом допустимы; автоматический профиль не валидирован.
            self.assertEqual(report['calibrated_profiles'],[]);self.assertIn('симметричны',report['profile_errors']['symmetric'])
