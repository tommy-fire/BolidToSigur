"""Portable file tests use synthetic identities/cards/photos, never live SQL."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import test_safe
import migration_data as d
import transfer_bundle as b
s=test_safe.s


def fixture(root,n=1):
    path=test_safe.Tests().fixture(root,n)
    meta=json.loads((root/'schema.json').read_text())
    meta['tables']['pList']={'columns':{'ID':'int','Name':'varchar'}}
    (root/'schema.json').write_text(json.dumps(meta))
    return path


def rewrite(src,dst,change):
    with zipfile.ZipFile(src) as z: data={n:z.read(n) for n in z.namelist()}
    change(data)
    with zipfile.ZipFile(dst,'w') as z:
        for n,v in data.items():z.writestr(n,v)


class BundleTests(unittest.TestCase):
    def test_roundtrip_offline_owner_numbers_dates_and_settings(self):
        import xlrd
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source';source.mkdir();path=fixture(source)
            marks=s.read_csv(source/'pMark.csv');marks[0]['CodeP']=test_safe.raw(0x00000123)
            s.write_csv(source/'pMark.csv',marks,list(marks[0]));path.unlink();s.prepare(source)
            marks[0].update(Start='2020-01-02T03:04:05',Finish='2030-01-02T11:12:13')
            s.write_csv(source/'pMark.csv',marks,list(marks[0]))
            rows=s.read_csv(path);rows[0].update(Approve='ДА',ObservedW34=rows[0]['CandidateW34']);s.write_csv(path,rows,s.REVIEW)
            settings={'start_column':'Start','expiry_column':'Finish','personal_mode':'notes','password':'not-to-save','allow_multicard_dates':True}
            package=b.pack(source,root/'save.bolid',settings)
            with zipfile.ZipFile(package) as z:
                meta=json.loads(z.read(b.MANIFEST));self.assertNotIn('password',meta['settings']);self.assertNotIn('allow_multicard_dates',meta['settings'])
            shutil.rmtree(source)
            with patch.object(s,'load_exporter',side_effect=AssertionError('SQL must not be loaded')):
                opened=b.unpack(package,root/'work');got=s.read_csv(opened)
                self.assertEqual(got[0]['RawCodeP'],rows[0]['RawCodeP']);self.assertEqual(got[0]['SourcePersonID'],'1');self.assertEqual(got[0]['ObservedW34'],rows[0]['ObservedW34'])
                st=json.loads((opened.parent/'transfer_settings.json').read_text());out=s.build(opened,st['expiry_column'],st['start_column'],st['personal_mode'])
            sh=xlrd.open_workbook(out/'ТЕСТ_Импорт_Sigur.xls').sheet_by_index(0);vals=dict(zip(sh.row_values(0),sh.row_values(1)))
            self.assertEqual(vals['Номер пропуска'],rows[0]['ObservedW34']);self.assertEqual(vals['Орион ID'],'1')
            self.assertEqual(vals['Начало действия пропуска'],'02.01.2020 03:04:05');self.assertEqual(vals['Окончание действия пропуска'],'02.01.2030 11:12:13')
            self.assertNotEqual(b.unpack(package,root/'work'),opened)

    def test_external_photo_cached_and_portable_repack(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'source';src.mkdir();path=fixture(src)
            photo=root/'external.png';Image.new('RGB',(5,6),'blue').save(photo)
            people=s.read_csv(src/'pList.csv');people[0]['Picture']=str(photo);s.write_csv(src/'pList.csv',people,list(people[0]))
            pack=b.pack(src,root/'first.bolid');photo.unlink();shutil.rmtree(src)
            path=b.unpack(pack,root/'work');details=d.enrich(path.parent)
            self.assertTrue(details['1']['photo']);self.assertEqual(s.read_csv(path.parent/'Предупреждения_данных.csv'),[])
            second=b.pack(path.parent,root/'second.bolid');shutil.rmtree(path.parent)
            path=b.unpack(second,root/'work');self.assertTrue(d.enrich(path.parent)['1']['photo'])

    def test_portable_never_reads_external_photo(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fixture(root)
            photo=root/'secret.png';Image.new('RGB',(3,3)).save(photo)
            people=s.read_csv(root/'pList.csv');people[0]['Picture']=str(photo);s.write_csv(root/'pList.csv',people,list(people[0]))
            (root/'PORTABLE.txt').write_text('1')
            self.assertEqual(d.enrich(root)['1']['photo'],'')
            self.assertTrue(s.read_csv(root/'Предупреждения_данных.csv'))

    def test_result_folders_and_unrelated_files_not_packed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fixture(root)
            (root/'password.txt').write_text('not-to-save');(root/'result_old').mkdir();(root/'result_old'/'old.xls').write_text('old')
            pack=b.pack(root,root/'test.bolid')
            with zipfile.ZipFile(pack) as z:
                self.assertNotIn('password.txt',z.namelist());self.assertFalse(any('result_' in n for n in z.namelist()))

    def test_checksum_failure_cleans_staging(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fixture(root);package=b.pack(root,root/'good.bolid')
            bad=root/'bad.bolid'
            rewrite(package,bad,lambda data:data.update({'pMark.csv':data['pMark.csv'].replace(b'1234',b'9876')+b' '}))
            with self.assertRaises(ValueError):b.unpack(bad,root/'work')
            self.assertEqual(list((root/'work').iterdir()),[])
            rewrite(package,bad,lambda data:data.update({'pMark.csv':data['pMark.csv'].replace(b'unknown',b'changed')}))
            with self.assertRaisesRegex(ValueError,'повреждён'):b.unpack(bad,root/'work')
            self.assertEqual(list((root/'work').iterdir()),[])

    def test_malicious_path_duplicate_version_link_size(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fixture(root);package=b.pack(root,root/'good.bolid');bad=root/'bad.bolid'
            def traversal(data):
                m=json.loads(data[b.MANIFEST]);payload=b'evil';name='../outside.txt'
                data[name]=payload;m['files'][name]={'size':4,'sha256':hashlib.sha256(payload).hexdigest()};data[b.MANIFEST]=json.dumps(m).encode()
            rewrite(package,bad,traversal)
            with self.assertRaises(ValueError):b.unpack(bad,root/'work')
            self.assertFalse((root/'outside.txt').exists())
            def future(data):
                m=json.loads(data[b.MANIFEST]);m['version']=999;data[b.MANIFEST]=json.dumps(m).encode()
            rewrite(package,bad,future)
            with self.assertRaises(ValueError):b.unpack(bad,root/'work')
            rewrite(package,bad,lambda data:data.update({'PLIST.CSV':data['pList.csv']}))
            with self.assertRaises(ValueError):b.unpack(bad,root/'work')
            with zipfile.ZipFile(package) as z:entries={n:z.read(n) for n in z.namelist()}
            with zipfile.ZipFile(bad,'w') as z:
                for n,v in entries.items():
                    i=zipfile.ZipInfo(n)
                    if n=='pList.csv':i.create_system=3;i.external_attr=(stat.S_IFLNK|0o777)<<16
                    z.writestr(i,v)
            with self.assertRaises(ValueError):b.unpack(bad,root/'work')
            with patch.object(b,'MAX_TOTAL',20):
                with self.assertRaises(ValueError):b.unpack(package,root/'work')
            self.assertEqual(list((root/'work').iterdir()),[])

    def test_owner_tampering_cannot_be_saved(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=fixture(root);rows=s.read_csv(path);rows[0]['SourcePersonID']='wrong';s.write_csv(path,rows,s.REVIEW)
            with self.assertRaises(ValueError):b.pack(root,root/'wrong.bolid')
            self.assertFalse((root/'wrong.bolid').exists())

    def test_failed_save_does_not_replace_existing_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fixture(root);package=b.pack(root,root/'good.bolid');original=package.read_bytes()
            with patch.object(b.os,'replace',side_effect=OSError('disk test')):
                with self.assertRaises(OSError):b.pack(root,package)
            self.assertEqual(package.read_bytes(),original);self.assertFalse(list(root.glob('.*.tmp')))
