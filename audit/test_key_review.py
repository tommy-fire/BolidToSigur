"""Additional deterministic key review; synthetic data, not hardware validation."""
import unittest, tempfile, json, random
from pathlib import Path
import test_safe
s = test_safe.s


def encode(serial):
    body = b'\x01' + serial
    data = body + bytes([s.crc8(body)])
    return '08' + ''.join('FE01' if b == 0 else 'FE02' if b == 254 else f'{b:02X}' for b in data)


class KeyReview(unittest.TestCase):
    def test_crc_standard_check_vector(self):
        self.assertEqual(s.crc8(b'123456789'), 0xA1)

    def test_full_serial_random_roundtrip(self):
        rng = random.Random(20260929)
        for _ in range(2000):
            serial = bytes(rng.randrange(256) for _ in range(6))
            abd, candidate = s.decode(encode(serial))
            self.assertEqual(candidate, serial[:4][::-1].hex().upper())
            self.assertEqual(abd[2:6], serial[4:][::-1].hex().upper())
            self.assertEqual(s.decode(abd, 'abd'), (abd, candidate))

    def test_every_single_bit_corruption_rejected(self):
        abd, _ = s.decode(encode(bytes.fromhex('FE0001023456')))
        data = bytes.fromhex(abd)
        for bit in range(64):
            corrupt = bytearray(data)
            corrupt[bit // 8] ^= 1 << (bit % 8)
            with self.assertRaises(ValueError):
                s.decode(corrupt.hex(), 'abd')

    def test_distinct_48bit_keys_collide_after_truncation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = test_safe.Tests().fixture(root, 2)
            people = s.read_csv(root/'pList.csv')
            people.append({**people[0], 'ID':'2', 'Name':'Другой', 'TabNumber':'T2'})
            s.write_csv(root/'pList.csv', people, list(people[0]))
            marks = s.read_csv(root/'pMark.csv')
            marks[0]['CodeP'] = encode(bytes.fromhex('123456780000'))
            marks[1].update(Owner='2', CodeP=encode(bytes.fromhex('123456780100')))
            self.assertNotEqual(marks[0]['CodeP'], marks[1]['CodeP'])
            s.write_csv(root/'pMark.csv', marks, list(marks[0]))
            path.unlink(); s.prepare(root)
            rows = s.read_csv(path)
            rows[0].update(Approve='ДА', ObservedW34=rows[0]['CandidateW34'])
            s.write_csv(path, rows, s.REVIEW)
            out = s.build(path)
            report = json.loads((out/'Отчёт.json').read_text())
            self.assertEqual(report['accepted'], 0)
            self.assertEqual(report['excluded'], 2)
            self.assertIn('Коллизия', s.read_csv(out/'Исключения.csv')[0]['Reason'])

    def test_duplicate_same_owner_rejects_both_deadlines(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = test_safe.Tests().fixture(root, 2)
            marks = s.read_csv(root/'pMark.csv')
            marks[1]['CodeP'] = marks[0]['CodeP']
            s.write_csv(root/'pMark.csv', marks, list(marks[0]))
            path.unlink(); s.prepare(root)
            rows = s.read_csv(path)
            for row, deadline in zip(rows, ['01.10.2026','01.10.2027']):
                row.update(Approve='ДА', ObservedW34=row['CandidateW34'])
                row['Срок действия'] = deadline
            s.write_csv(path, rows, s.REVIEW)
            out = s.build(path)
            report = json.loads((out/'Отчёт.json').read_text())
            self.assertEqual((report['accepted'], report['excluded']), (0, 2))
