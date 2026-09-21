import json
import tempfile
import unittest
from pathlib import Path

from module.config_loader import SettingsLoadError, load_settings


class ConfigLoaderTests(unittest.TestCase):
    def write(self, root: Path, value):
        p=root/'settings.json'
        p.write_text(json.dumps(value),encoding='utf-8')
        return p

    def test_missing_file_returns_safe_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            cfg=load_settings(Path(td)/'missing.json')
        self.assertIn('camera',cfg)
        self.assertIn('cam0',cfg['camera'])
        self.assertFalse(cfg['camera']['cam0']['tuning_file_override']['enabled'])

    def test_empty_object_gets_modern_camera_shape(self):
        with tempfile.TemporaryDirectory() as td:
            cfg=load_settings(self.write(Path(td),{}))
        self.assertEqual(cfg['camera']['cam0']['output']['hdmi_port'],0)
        self.assertEqual(cfg['camera']['cam1']['output']['hdmi_port'],1)
        self.assertEqual(
            cfg['camera']['cam0']['tuning_file_override'],
            {'enabled':False,'path':'resources/tuning_files/imx477.json'},
        )

    def test_legacy_geometry_is_migrated(self):
        legacy={'geometry':{'cam0':{'rotate_180':True}}}
        with tempfile.TemporaryDirectory() as td:
            cfg=load_settings(self.write(Path(td),legacy))
        self.assertTrue(cfg['camera']['cam0']['geometry']['rotate_180'])
        self.assertNotIn('geometry',cfg)

    def test_legacy_output_is_migrated(self):
        legacy={'output':{'cam0':{'hdmi_port':1}}}
        with tempfile.TemporaryDirectory() as td:
            cfg=load_settings(self.write(Path(td),legacy))
        self.assertEqual(cfg['camera']['cam0']['output']['hdmi_port'],1)
        self.assertNotIn('output',cfg)

    def test_existing_camera_values_are_preserved(self):
        data={'camera':{'cam0':{
            'phase_lock':False,
            'tuning_file_override':{'enabled':True,'path':'custom.json'},
        }}}
        with tempfile.TemporaryDirectory() as td:
            cfg=load_settings(self.write(Path(td),data))
        self.assertFalse(cfg['camera']['cam0']['phase_lock'])
        self.assertEqual(cfg['camera']['cam0']['tuning_file_override']['path'],'custom.json')
        self.assertTrue(cfg['camera']['cam0']['tuning_file_override']['enabled'])

    def test_malformed_json_raises_actionable_error(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'settings.json'
            p.write_text('{"camera":',encoding='utf-8')
            with self.assertRaises(SettingsLoadError) as cm:
                load_settings(p)
        self.assertIn('JSON',cm.exception.summary)

    def test_known_object_section_rejects_wrong_type_with_path(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.write(Path(td), {"preview": "broken"})
            with self.assertRaises(SettingsLoadError) as cm:
                load_settings(p)
        self.assertIn("invalid structure", cm.exception.summary)
        self.assertIn("preview", cm.exception.detail)
        self.assertIn("object", cm.exception.detail)

    def test_nested_camera_object_rejects_wrong_type_with_path(self):
        data = {"camera": {"cam0": {"geometry": []}}}
        with tempfile.TemporaryDirectory() as td:
            p = self.write(Path(td), data)
            with self.assertRaises(SettingsLoadError) as cm:
                load_settings(p)
        self.assertIn("camera.cam0.geometry", cm.exception.detail)

    def test_numeric_step_table_rejects_non_numeric_member(self):
        data = {"arrays": {"fps_steps": [24, "twenty-five", 30]}}
        with tempfile.TemporaryDirectory() as td:
            p = self.write(Path(td), data)
            with self.assertRaises(SettingsLoadError) as cm:
                load_settings(p)
        self.assertIn("arrays.fps_steps[1]", cm.exception.detail)

    def test_unknown_top_level_key_remains_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = load_settings(self.write(Path(td), {"future_feature": {"x": 1}}))
        self.assertEqual(cfg["future_feature"], {"x": 1})

    def test_current_repository_settings_pass_structural_validation(self):
        current = Path(__file__).resolve().parents[1] / "src" / "settings.json"
        cfg = load_settings(current)
        self.assertIn("camera", cfg)


    def test_non_utf8_raises_actionable_error(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'settings.json'
            p.write_bytes(b'\xff\xfe\x00')
            with self.assertRaises(SettingsLoadError) as cm:
                load_settings(p)
        self.assertIn('UTF-8',cm.exception.summary)

    def test_non_object_root_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.write(Path(td),[])
            with self.assertRaises(SettingsLoadError) as cm:
                load_settings(p)
        self.assertIn('top-level object',cm.exception.summary)


if __name__=='__main__':
    unittest.main()
