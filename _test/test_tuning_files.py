import json
import tempfile
import unittest
from pathlib import Path

from src.module.tuning_files import resolve_tuning_override, tuning_json_problem


VALID = {"version": 2.0, "target": "pisp", "algorithms": []}


class TuningJsonProblemTests(unittest.TestCase):
    def test_valid_pisp_v2(self):
        self.assertIsNone(tuning_json_problem(VALID))

    def test_non_object_rejected(self):
        self.assertIn("not an object", tuning_json_problem([]))

    def test_missing_target_rejected(self):
        self.assertIn('expected "pisp"', tuning_json_problem({"algorithms": []}))

    def test_vc4_target_rejected(self):
        self.assertIn("VC4", tuning_json_problem({"target": "bcm2835", "algorithms": []}))

    def test_algorithms_missing_rejected(self):
        self.assertIn("algorithms", tuning_json_problem({"target": "pisp"}))

    def test_algorithms_wrong_type_rejected(self):
        self.assertIn("algorithms", tuning_json_problem({"target": "pisp", "algorithms": {}}))


class ResolveTuningOverrideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative, data=VALID, raw=None):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if raw is None:
            path.write_text(json.dumps(data), encoding="utf-8")
        else:
            path.write_bytes(raw)
        return path

    def test_none_is_disabled(self):
        self.assertEqual(resolve_tuning_override(None, self.root), (None, "disabled"))

    def test_non_mapping_is_disabled(self):
        self.assertEqual(resolve_tuning_override([], self.root), (None, "disabled"))

    def test_disabled_ignores_invalid_path(self):
        self.assertEqual(
            resolve_tuning_override({"enabled": False, "path": "/does/not/exist"}, self.root),
            (None, "disabled"),
        )

    def test_enabled_without_path_is_rejected(self):
        path, reason = resolve_tuning_override({"enabled": True}, self.root)
        self.assertIsNone(path)
        self.assertIn("no path", reason)

    def test_blank_path_is_rejected(self):
        path, reason = resolve_tuning_override({"enabled": True, "path": "   "}, self.root)
        self.assertIsNone(path)
        self.assertIn("no path", reason)

    def test_relative_path_resolves_against_repo_root(self):
        expected = self.write("resources/tuning_files/custom.json")
        path, reason = resolve_tuning_override(
            {"enabled": True, "path": "resources/tuning_files/custom.json"},
            self.root,
        )
        self.assertEqual(reason, "ok")
        self.assertEqual(path, expected.resolve())

    def test_absolute_path_is_accepted(self):
        expected = self.write("absolute.json")
        path, reason = resolve_tuning_override(
            {"enabled": True, "path": str(expected)},
            self.root,
        )
        self.assertEqual((path, reason), (expected.resolve(), "ok"))

    def test_tilde_is_expanded(self):
        # Expansion is deterministic even though this path should not exist in
        # the isolated test environment.
        path, reason = resolve_tuning_override(
            {"enabled": True, "path": "~/definitely-no-cinemate-tuning.json"},
            self.root,
        )
        self.assertIsNone(path)
        self.assertIn(str(Path.home()), reason)

    def test_missing_file_falls_back(self):
        path, reason = resolve_tuning_override(
            {"enabled": True, "path": "missing.json"},
            self.root,
        )
        self.assertIsNone(path)
        self.assertIn("file not found", reason)

    def test_directory_is_not_a_tuning_file(self):
        (self.root / "dir").mkdir()
        path, reason = resolve_tuning_override(
            {"enabled": True, "path": "dir"},
            self.root,
        )
        self.assertIsNone(path)
        self.assertIn("file not found", reason)

    def test_invalid_json_is_rejected(self):
        self.write("bad.json", raw=b'{"target":"pisp",')
        path, reason = resolve_tuning_override(
            {"enabled": True, "path": "bad.json"},
            self.root,
        )
        self.assertIsNone(path)
        self.assertIn("not valid JSON", reason)

    def test_non_utf8_is_rejected(self):
        self.write("binary.json", raw=b"\xff\xfe\x00")
        path, reason = resolve_tuning_override(
            {"enabled": True, "path": "binary.json"},
            self.root,
        )
        self.assertIsNone(path)
        self.assertIn("UTF-8", reason)

    def test_wrong_target_is_rejected(self):
        self.write("vc4.json", {"target": "bcm2835", "algorithms": []})
        path, reason = resolve_tuning_override(
            {"enabled": True, "path": "vc4.json"},
            self.root,
        )
        self.assertIsNone(path)
        self.assertIn("VC4", reason)

    def test_missing_algorithms_is_rejected(self):
        self.write("old.json", {"target": "pisp"})
        path, reason = resolve_tuning_override(
            {"enabled": True, "path": "old.json"},
            self.root,
        )
        self.assertIsNone(path)
        self.assertIn("algorithms", reason)

    def test_symlink_to_valid_file_is_accepted(self):
        target = self.write("real.json")
        link = self.root / "link.json"
        link.symlink_to(target)
        path, reason = resolve_tuning_override(
            {"enabled": True, "path": "link.json"},
            self.root,
        )
        self.assertEqual(reason, "ok")
        self.assertEqual(path, target.resolve())


if __name__ == "__main__":
    unittest.main()
