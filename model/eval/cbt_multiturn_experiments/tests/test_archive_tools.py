"""Publication-check regressions using only synthetic temporary files."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "tools/validate_archive.py"
SPEC = importlib.util.spec_from_file_location("archive_validator", SCRIPT)
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class ArchiveValidationTests(unittest.TestCase):
    def seal(self, directory):
        (directory / "provenance.json").write_text(json.dumps({"files": []}))
        lines = []
        for path in sorted(directory.iterdir()):
            if path.name != "CHECKSUMS.sha256":
                lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name)
        (directory / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n")

    def check(self, filename, content, message=None):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / filename).write_text(content)
            self.seal(directory)
            with patch.object(VALIDATOR, "ROOT", directory):
                if message:
                    with self.assertRaisesRegex(ValueError, message):
                        VALIDATOR.validate()
                else:
                    self.assertTrue(VALIDATOR.validate()["valid"])

    def test_clean_synthetic_files_pass(self):
        self.check("README.md", "Synthetic public archive\n")

    def test_raw_input_name_is_rejected(self):
        self.check("cases.json", "[]", "Forbidden file")

    def test_transcript_json_is_rejected(self):
        self.check("example.json", json.dumps({"utterance": "synthetic text"}), "Transcript-bearing")

    def test_secret_candidate_is_rejected_without_echoing_value(self):
        synthetic = "sk-" + "X" * 32
        self.check("example.txt", synthetic, "Sensitive-pattern")

    def test_broken_relative_link_is_rejected(self):
        self.check("README.md", "[missing](missing.md)", "Broken local link")

    def test_checksum_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / "example.txt"
            path.write_text("before")
            self.seal(directory)
            path.write_text("after")
            with patch.object(VALIDATOR, "ROOT", directory), self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                VALIDATOR.validate()

    def test_aihub_dialogue_manifest_is_rejected(self):
        manifest = {"session_count": 1, "files": [{"path": "example.md", "case_id": "R001",
            "source_session_id": "aihub_synthetic", "rendered_sha256": "invalid"}]}
        self.check("dialogue_results_manifest.json", json.dumps(manifest), "Non-approved dialogue")

    def test_approved_case_must_have_exact_source_id(self):
        manifest = {"session_count": 1, "files": [{"path": "example.md", "case_id": "R002",
            "source_session_id": "cactus_other", "rendered_sha256": "invalid"}]}
        self.check("dialogue_results_manifest.json", json.dumps(manifest), "Non-approved dialogue")

    def test_dialogue_path_traversal_is_rejected(self):
        manifest = {"session_count": 1, "files": [{"path": "../example.md", "case_id": "R002",
            "source_session_id": "cactus_0207", "rendered_sha256": "invalid"}]}
        self.check("dialogue_results_manifest.json", json.dumps(manifest), "Invalid dialogue path")


if __name__ == "__main__":
    unittest.main()
