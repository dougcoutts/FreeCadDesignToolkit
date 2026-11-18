"""Tests for the saved-model evidence preflight, independent of FreeCAD."""
import hashlib
import os
from pathlib import Path
import tempfile
import types
import sys
import unittest
from unittest.mock import patch

from journal_integration import verify_saved_model, ENV


class SavedModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.model = Path(self.temp.name) / "model.FCStd"
        self.model.write_bytes(b"saved model")
        self.doc = types.SimpleNamespace(Name='TestDoc', FileName=str(self.model))
        self.gui_doc = types.SimpleNamespace(Modified=False)
        self.gui_module = types.SimpleNamespace(getDocument=lambda name: self.gui_doc if name == 'TestDoc' else None)
        gui_patch = patch.dict(sys.modules, {'FreeCADGui': self.gui_module})
        gui_patch.start()
        self.addCleanup(gui_patch.stop)

    def test_saved_model_is_accepted(self):
        path, digest = verify_saved_model(self.doc)
        self.assertEqual(path, str(self.model.resolve()))
        self.assertEqual(digest, hashlib.sha256(b"saved model").hexdigest())
        self.assertEqual(verify_saved_model(self.doc, digest), (path, digest))

    def test_missing_gui_module_is_rejected(self):
        with patch.dict(sys.modules, {'FreeCADGui': None}):
            with self.assertRaisesRegex(ValueError, "Cannot verify FreeCAD GUI"):
                verify_saved_model(self.doc)

    def test_document_without_name_is_rejected(self):
        del self.doc.Name
        with self.assertRaisesRegex(ValueError, "Cannot identify FreeCAD document"):
            verify_saved_model(self.doc)

    def test_gui_modified_detects_label_only_edit(self):
        # FreeCAD 1.1.4: doc.isSaved() stays True for an unsaved label edit.
        self.doc.isSaved = lambda: True
        self.gui_doc.Modified = True
        with self.assertRaisesRegex(ValueError, "unsaved changes"):
            verify_saved_model(self.doc)

    def test_missing_matching_gui_document_is_rejected(self):
        self.doc.Name = 'OtherDocument'
        with self.assertRaisesRegex(ValueError, "No matching FreeCAD GUI document"):
            verify_saved_model(self.doc)

    def test_gui_modified_flag_unavailable_is_rejected(self):
        self.gui_doc = types.SimpleNamespace()
        with self.assertRaisesRegex(ValueError, "Cannot verify FreeCAD GUI"):
            verify_saved_model(self.doc)

    def test_missing_model_is_rejected(self):
        self.doc.FileName = str(self.model.with_name("missing.FCStd"))
        with self.assertRaises(FileNotFoundError):
            verify_saved_model(self.doc)

    def test_explicit_empty_expected_hash_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "changed during validation"):
            verify_saved_model(self.doc, expected_sha256="")

    def test_equivalent_expected_path_is_accepted(self):
        nested = self.model.parent / "nested"
        nested.mkdir()
        alias = nested / ".." / self.model.name
        path, _ = verify_saved_model(self.doc, expected_path=alias)
        self.assertEqual(path, str(self.model.resolve()))

    def test_explicit_verification_runs_when_journaling_is_disabled(self):
        with patch.dict(os.environ, {ENV: ""}), patch.object(
            self.gui_module, 'getDocument', return_value=self.gui_doc
        ) as lookup:
            verify_saved_model(self.doc)
        lookup.assert_called_once_with(self.doc.Name)
