import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from flask import Flask
from module.app.main import routes


def cube_text(size=2,title='Test'):
    rows=[]
    for b in range(size):
        for g in range(size):
            for r in range(size):
                d=max(1,size-1)
                rows.append(f'{r/d:.6f} {g/d:.6f} {b/d:.6f}')
    return '\n'.join([
        f'TITLE "{title}"',
        f'LUT_3D_SIZE {size}',
        'DOMAIN_MIN 0 0 0',
        'DOMAIN_MAX 1 1 1',
        *rows,
        ''
    ])


class LutRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.lutdir=Path(self.tmp.name)
        self.patch=mock.patch.object(routes,'_LUT_DIR',str(self.lutdir))
        self.patch.start()
        app=Flask(__name__)
        app.register_blueprint(routes.main_routes)
        app.testing=True
        self.client=app.test_client()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def write_cube(self,name='test.cube',text=None):
        p=self.lutdir/name
        p.write_text(text if text is not None else cube_text(),encoding='utf-8')
        return p

    def test_safe_name_rejects_traversal_and_wrong_extensions(self):
        self.assertEqual(routes._lut_safe_name('look.cube'),'look.cube')
        for bad in ('../look.cube','dir/look.cube','look.txt','look.cube/extra',''):
            self.assertIsNone(routes._lut_safe_name(bad))
        self.assertIsNone(routes._lut_safe_name(None))

    def test_header_accepts_3d_cube(self):
        p=self.write_cube()
        hdr=routes._lut_header(str(p))
        self.assertEqual(hdr['size'],2)
        self.assertEqual(hdr['title'],'Test')
        self.assertEqual(hdr['domain_min'],[0.0,0.0,0.0])

    def test_header_rejects_1d_lut(self):
        p=self.write_cube(text='LUT_1D_SIZE 2\n0 0 0\n1 1 1\n')
        self.assertIsNone(routes._lut_header(str(p)))

    def test_header_rejects_missing_or_invalid_size(self):
        for text in ('TITLE "x"\n0 0 0\n','LUT_3D_SIZE 1\n0 0 0\n'):
            p=self.write_cube(text=text)
            self.assertIsNone(routes._lut_header(str(p)))

    def test_catalog_hides_validation_lut_by_default(self):
        self.write_cube('visible.cube')
        self.write_cube('_identity.cube')
        names=[x['name'] for x in self.client.get('/api/luts').get_json()['luts']]
        self.assertEqual(names,['visible.cube'])

    def test_catalog_can_include_validation_lut(self):
        self.write_cube('_identity.cube')
        names=[x['name'] for x in self.client.get('/api/luts?include_validation=1').get_json()['luts']]
        self.assertEqual(names,['_identity.cube'])

    def test_catalog_uses_metadata_and_hash(self):
        p=self.write_cube('look.cube')
        (self.lutdir/'look.json').write_text(json.dumps({
            'display_name':'My Look',
            'interpolation':'trilinear',
            'official_cinepi':True,
            'recommended_mix_percent':80,
        }),encoding='utf-8')
        item=self.client.get('/api/luts').get_json()['luts'][0]
        self.assertEqual(item['display_name'],'My Look')
        self.assertEqual(item['interpolation'],'trilinear')
        self.assertTrue(item['official_cinepi'])
        self.assertEqual(item['recommended_mix_percent'],80)
        self.assertEqual(len(item['sha256']),64)

    def test_bad_sidecar_does_not_break_catalog(self):
        self.write_cube('look.cube')
        (self.lutdir/'look.json').write_text('{',encoding='utf-8')
        r=self.client.get('/api/luts')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.get_json()['luts'][0]['name'],'look.cube')

    def test_unknown_interpolation_falls_back_to_tetrahedral(self):
        self.write_cube('look.cube')
        (self.lutdir/'look.json').write_text(
            json.dumps({'interpolation':'made-up'}),encoding='utf-8'
        )
        item=self.client.get('/api/luts').get_json()['luts'][0]
        self.assertEqual(item['interpolation'],'tetrahedral')

    def test_missing_lut_returns_404(self):
        self.assertEqual(self.client.get('/api/luts/missing.cube').status_code,404)

    def test_wrong_extension_returns_404(self):
        (self.lutdir/'secret.txt').write_text('secret')
        self.assertEqual(self.client.get('/api/luts/secret.txt').status_code,404)

    def test_gzip_transport_round_trips_exact_cube(self):
        p=self.write_cube('look.cube')
        raw=p.read_bytes()
        r=self.client.get('/api/luts/look.cube',headers={'Accept-Encoding':'gzip'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.headers.get('Content-Encoding'),'gzip')
        self.assertEqual(gzip.decompress(r.data),raw)
        self.assertIn('max-age=86400',r.headers.get('Cache-Control',''))

    def test_plain_transport_round_trips_exact_cube(self):
        p=self.write_cube('look.cube')
        r=self.client.get('/api/luts/look.cube')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.data,p.read_bytes())

    def test_official_pack_missing_returns_404(self):
        self.assertEqual(self.client.get('/api/luts/official-pack.zip').status_code,404)

    def test_official_pack_is_downloadable(self):
        payload=b'PK\x03\x04fakezip'
        (self.lutdir/'cinepi-official-lut-pack.zip').write_bytes(payload)
        r=self.client.get('/api/luts/official-pack.zip')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.data,payload)
        self.assertIn('attachment',r.headers.get('Content-Disposition',''))


if __name__=='__main__':
    unittest.main()
