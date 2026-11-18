"""Tests for the saved-model evidence preflight, independent of FreeCAD."""
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
        self.assertEqual(len(digest), 64)
        self.assertEqual(verify_saved_model(self.doc, digest), (path, digest))

    def test_unsaved_document_is_rejected(self):
        self.doc.FileName = ""
        with self.assertRaisesRegex(ValueError, "Save"):
            verify_saved_model(self.doc)

    def test_modified_document_is_rejected(self):
        self.gui_doc.Modified = True
        with self.assertRaisesRegex(ValueError, "unsaved changes"):
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

    def test_changed_file_is_rejected(self):
        _, before = verify_saved_model(self.doc)
        self.model.write_bytes(b"new saved model")
        with self.assertRaisesRegex(ValueError, "changed during validation"):
            verify_saved_model(self.doc, before)

    def test_changed_document_path_is_rejected(self):
        path, digest = verify_saved_model(self.doc)
        other = self.model.with_name("other.FCStd")
        other.write_bytes(b"saved model")
        self.doc.FileName = str(other)
        with self.assertRaisesRegex(ValueError, "different model"):
            verify_saved_model(self.doc, digest, expected_path=path)

    def test_disabled_journaling_remains_opt_in(self):
        with patch.dict(os.environ, {ENV: ""}):
            self.assertFalse(os.environ.get(ENV))
