import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

from module.app import create_app


class DummySignal:
    def subscribe(self, callback):
        self.callback = callback


class DummyRedis:
    def __init__(self):
        self.redis_parameter_changed = DummySignal()

    def get_value(self,key,default=None):
        values={
            'iso':800,'shutter_a':180,'fps_actual':24,'wb_user':5600,
            'resolution_switching':'0',
        }
        return values.get(getattr(key,'value',key),default)


class DummyController:
    iso_steps=[100,200,400,800]
    shutter_a_steps_dynamic=[90,180]
    fps_steps_dynamic=[24,25,30]
    wb_steps=[3200,4400,5600]
    def add_resolution_change_callback(self,cb):
        self.cb=cb


class DummyGui:
    def set_socketio(self,s): self.socketio=s
    def get_background_color(self): return 'black'
    def populate_values(self): return {}


class DummySensor:
    def get_available_resolutions(self):
        return {0:{'width':3936,'height':2176,'bit_depth':12}}


class MonitoringUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template=(ROOT/'src/module/app/templates/template.html').read_text()
        cls.clips=(ROOT/'src/module/app/templates/clips.html').read_text()
        cls.engine=(ROOT/'src/module/app/static/js/cube-lut-engine.js').read_text()
        cls.css=(ROOT/'src/module/app/static/css/cinemate-responsive.css').read_text()
        cls.sw=(ROOT/'src/module/app/static/sw.js').read_text()

    def test_index_template_renders(self):
        app,_=create_app(DummyRedis(),DummyController(),DummyGui(),DummySensor())
        app.testing=True
        with app.test_client() as c:
            r=c.get('/',headers={'Host':'cinepi.local:5000'})
        self.assertEqual(r.status_code,200)
        html=r.get_data(as_text=True)
        self.assertIn('id="btn-zebra"',html)
        self.assertIn('id="btn-peak"',html)
        self.assertIn('id="wave-ov"',html)
        self.assertIn('id="vect-ov"',html)
        self.assertIn('data-stream-port="8000"',html)
        self.assertNotIn('http://cinepi.local:8000/stream',html)

    def test_zebra_defaults_to_90_ire(self):
        self.assertIn("localStorage.getItem('cinepiZebraIRE')||90",self.template)
        self.assertIn('[70,80,85,90,95,100]',self.template)
        self.assertIn("('Z '+zebraIRE)",self.template)

    def test_zebra_hold_works_for_mouse_and_touch(self):
        self.assertIn("bz.addEventListener('mousedown'",self.template)
        self.assertIn("bz.addEventListener('pointerdown'",self.template)
        self.assertIn("},550)",self.template)
        self.assertIn("if(e.pointerType==='mouse')return",self.template)

    def test_zebra_long_press_disables_text_selection(self):
        self.assertIn("bz.style.userSelect='none'",self.template)
        self.assertIn("bz.style.webkitTouchCallout='none'",self.template)
        self.assertIn("m.addEventListener('selectstart'",self.template)
        self.assertIn("sel.removeAllRanges()",self.template)

    def test_monitor_overlay_stays_above_lut_canvas(self):
        self.assertIn('display:none;z-index:7',self.template)
        self.assertIn("zc.style.zIndex='7'",self.template)

    def test_monitoring_v2_uses_full_range_bt709(self):
        self.assertIn('Monitoring v2',self.template)
        self.assertIn('rr*54+gg*183+bb*19',self.template)
        self.assertNotIn('(y-16)*255/219',self.template)

    def test_peaking_uses_denoised_sobel_and_adaptive_threshold(self):
        self.assertIn('Gaussian',self.template)
        self.assertIn('Sobel',self.template)
        self.assertIn('noise*2.2+18',self.template)
        self.assertIn('local-max',self.template)

    def test_lut_fetch_cache_is_content_addressed(self):
        self.assertIn("cacheKey = name + (sha ? '@' + sha : '')",self.engine)
        self.assertIn("?v=' + encodeURIComponent(sha)",self.engine)

    def test_lut_upload_resets_unpack_flip_before_3d_texture(self):
        self.assertIn('UNPACK_FLIP_Y_WEBGL, false',self.engine)

    def test_lut_engine_contains_gpu_self_test(self):
        self.assertIn('Renderer.prototype._selfTest',self.engine)
        self.assertIn("report('lut-self-test'",self.engine)
        self.assertIn('readPixels',self.engine)

    def test_camera_and_clips_load_same_lut_engine_revision(self):
        marker='/static/js/cube-lut-engine.js?v=20260921a'
        self.assertIn(marker,self.template)
        self.assertIn(marker,self.clips)

    def test_pwa_cache_revision_is_current(self):
        self.assertIn("cinepi-shell-v24",self.sw)


if __name__=='__main__':
    unittest.main()
