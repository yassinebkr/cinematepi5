import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LUTS=ROOT/'luts'
GENERATOR=ROOT/'tools/generate_cinepi_luts.py'


def load_generator():
    spec=importlib.util.spec_from_file_location('cinepi_lut_generator',GENERATOR)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OfficialLutTests(unittest.TestCase):
    def test_manifest_hashes_match_files(self):
        manifest=json.loads((LUTS/'cinepi-official-manifest.json').read_text())
        self.assertGreaterEqual(len(manifest['looks']),5)
        for item in manifest['looks']:
            p=LUTS/item['file']
            self.assertTrue(p.is_file(),item['file'])
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),item['sha256'])

    def test_every_official_cube_has_sidecar(self):
        for p in LUTS.glob('cinepi-*.cube'):
            side=p.with_suffix('.json')
            self.assertTrue(side.is_file(),p.name)
            meta=json.loads(side.read_text())
            self.assertTrue(meta.get('official_cinepi'),p.name)
            self.assertTrue(meta.get('redistributable_by_cinepi'),p.name)
            self.assertEqual(meta.get('generator'),'tools/generate_cinepi_luts.py')
            self.assertEqual(meta.get('sha256'),hashlib.sha256(p.read_bytes()).hexdigest())

    def test_reference_lut_is_identity(self):
        p=LUTS/'cinepi-rec709-reference.cube'
        rows=[]
        size=None
        for line in p.read_text().splitlines():
            line=line.strip()
            if not line or line.startswith('#'): continue
            if line.startswith('LUT_3D_SIZE'):
                size=int(line.split()[1]); continue
            if line.startswith(('TITLE','DOMAIN_')): continue
            parts=line.split()
            if len(parts)==3:
                rows.append(tuple(map(float,parts)))
        self.assertEqual(len(rows),size**3)
        den=size-1
        i=0
        for b in range(size):
            for g in range(size):
                for r in range(size):
                    expected=(r/den,g/den,b/den)
                    got=rows[i];i+=1
                    for a,e in zip(got,expected):
                        self.assertAlmostEqual(a,e,places=8)

    def test_generator_is_deterministic_in_temp_directory(self):
        mod=load_generator()
        with tempfile.TemporaryDirectory() as td:
            old=mod.OUT
            try:
                mod.OUT=Path(td)
                mod.main()
                for item in json.loads((mod.OUT/'cinepi-official-manifest.json').read_text())['looks']:
                    committed=LUTS/item['file']
                    regenerated=mod.OUT/item['file']
                    self.assertEqual(regenerated.read_bytes(),committed.read_bytes(),item['file'])
            finally:
                mod.OUT=old

    def test_no_third_party_lut_is_part_of_shipping_directory(self):
        names=[p.name.lower() for p in LUTS.glob('*.cube')]
        self.assertFalse(any(name.startswith('free-') for name in names),names)

    def test_cube_sizes_are_valid(self):
        for p in LUTS.glob('cinepi-*.cube'):
            size=None
            rows=0
            for line in p.read_text().splitlines():
                s=line.split('#',1)[0].strip()
                if not s: continue
                if s.startswith('LUT_3D_SIZE'):
                    size=int(s.split()[1])
                elif s[0] in '+-.0123456789' and len(s.split())>=3:
                    rows+=1
            self.assertIsNotNone(size,p.name)
            self.assertEqual(rows,size**3,p.name)


if __name__=='__main__':
    unittest.main()
