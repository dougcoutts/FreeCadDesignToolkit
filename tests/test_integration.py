import json, os, tempfile, unittest
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from journal_integration import record_fem, record_cad, record_cad_artifact, record_validation, ENV
from journal_manager import read_events, sha256

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.old=os.environ.get(ENV)
        os.environ[ENV]=str(self.root/'journal')
        self.addCleanup(self.restore)
    def restore(self):
        if self.old is None: os.environ.pop(ENV,None)
        else: os.environ[ENV]=self.old
    def file(self,name,data):
        p=self.root/name
        p.write_text(data)
        return p
    def test_fem_two_runs_are_append_only_and_hashed(self):
        config=self.file('cfg.json','{"mesh": {}}')
        model=self.file('model.FCStd','placeholder test bytes')
        summary=self.file('summary.json','{"max_down_disp_mm":9.5}')
        result={'model':{'tag':'V4'},'solver':{'finished':True},'max_down_disp_mm':9.5,'equilibrium':{'error_pct':0.02}}
        a=record_fem('screening',result,summary,config,model)
        b=record_fem('screening',result,summary,config,model)
        self.assertNotEqual(a,b)
        events=read_events(self.root/'journal')
        self.assertEqual(len(events),2)
        self.assertEqual(events[0]['data']['max_down_disp_mm'],9.5)
        self.assertTrue(any(x['sha256']==sha256(summary) for x in events[0]['artifact_refs']))
        self.assertIn(json.loads(a.read_text())['event_id'], [e['event_id'] for e in events])
    def test_failed_solver_rejected(self):
        p=self.file('summary.json','{}')
        with self.assertRaises(ValueError):
            record_fem('contact',{'solver':{'final_finished':False}},p,p)
        self.assertEqual(read_events(self.root/'journal'),[])
    def test_headless_cad_and_validation(self):
        p=self.file('v4.FCStd','test bytes')
        script=self.file('build.py','pass')
        with patch.dict(sys.modules, {'FreeCADGui': None}):
            event_path = record_cad_artifact(p, script, 'V4')
        self.assert_cad_evidence(event_path, p, script)
        report=self.file('validation.json','{"solid": {"valid": true}}')
        record_validation({'solid':{'valid':True}, 'boolean_retries':0},p,report)
        self.assertEqual({e['event_type'] for e in read_events(self.root/'journal')},{'design_revision','observation'})

    def cad_document(self, model_path):
        gui_doc = SimpleNamespace(Modified=False)
        doc = SimpleNamespace(Name='Shelf', FileName=str(model_path))
        gui = SimpleNamespace(getDocument=lambda name: gui_doc if name == doc.Name else None)
        gui_patch = patch.dict(sys.modules, {'FreeCADGui': gui})
        gui_patch.start()
        self.addCleanup(gui_patch.stop)
        return doc, gui_doc

    def assert_cad_evidence(self, event_path, model, script):
        event = json.loads(event_path.read_text(encoding='utf-8'))
        self.assertEqual(event['event_type'], 'design_revision')
        self.assertEqual(event['design_revision'], 'V4')
        self.assertEqual(event['artifact_refs'], [
            {'role': 'model', 'path': str(model.resolve()), 'sha256': sha256(model)},
            {'role': 'build_script', 'path': str(script.resolve()), 'sha256': sha256(script)},
        ])
        self.assertEqual(event['data']['model_sha256'], event['artifact_refs'][0]['sha256'])

    def test_interactive_cad_records_saved_document(self):
        model = self.file('v4.FCStd', 'model bytes')
        script = self.file('build.py', 'pass')
        doc, _ = self.cad_document(model)
        event_path = record_cad(doc, model, script, 'V4')
        self.assert_cad_evidence(event_path, model, script)

    def test_interactive_cad_rejects_unsaved_document(self):
        model = self.file('v4.FCStd', 'model bytes')
        script = self.file('build.py', 'pass')
        doc, _ = self.cad_document('')
        with self.assertRaisesRegex(ValueError, 'Save FreeCAD document'):
            record_cad(doc, model, script)
        self.assertEqual(read_events(self.root/'journal'), [])

    def test_interactive_cad_rejects_path_mismatch(self):
        model = self.file('v4.FCStd', 'model bytes')
        other = self.file('other.FCStd', 'model bytes')
        script = self.file('build.py', 'pass')
        doc, _ = self.cad_document(other)
        with self.assertRaisesRegex(ValueError, 'different model'):
            record_cad(doc, model, script)
        self.assertEqual(read_events(self.root/'journal'), [])

    def test_interactive_cad_rejects_hash_mismatch_before_append(self):
        model = self.file('v4.FCStd', 'model bytes')
        script = self.file('build.py', 'pass')
        doc, _ = self.cad_document(model)

        def hash_with_model_change(path):
            if path == script.resolve():
                model.write_text('changed model bytes')
            return sha256(path)

        with patch('journal_integration.sha256', side_effect=hash_with_model_change):
            with self.assertRaisesRegex(ValueError, 'model changed'):
                record_cad(doc, model, script)
        self.assertEqual(read_events(self.root/'journal'), [])

    def test_interactive_cad_rechecks_modified_state_before_append(self):
        model = self.file('v4.FCStd', 'model bytes')
        script = self.file('build.py', 'pass')
        doc, gui_doc = self.cad_document(model)

        def hash_with_gui_edit(path):
            if path == script.resolve():
                gui_doc.Modified = True
            return sha256(path)

        with patch('journal_integration.sha256', side_effect=hash_with_gui_edit):
            with self.assertRaisesRegex(ValueError, 'unsaved changes'):
                record_cad(doc, model, script)
        self.assertEqual(read_events(self.root/'journal'), [])

    def test_headless_cad_requires_both_evidence_files(self):
        model = self.file('v4.FCStd', 'model bytes')
        script = self.file('build.py', 'pass')
        with self.assertRaises(FileNotFoundError):
            record_cad_artifact(self.root/'missing.FCStd', script)
        with self.assertRaises(FileNotFoundError):
            record_cad_artifact(model, self.root/'missing.py')
        with self.assertRaises(ValueError):
            record_cad_artifact(model, None)
        self.assertEqual(read_events(self.root/'journal'), [])

    def test_disabled_is_noop(self):
        os.environ.pop(ENV,None)
        self.assertIsNone(record_cad(None, 'missing.FCStd', 'missing.py'))
        self.assertIsNone(record_cad_artifact('missing.FCStd', 'missing.py'))
        self.assertFalse((self.root/'journal').exists())

    def test_validation_requires_both_evidence_files(self):
        model=self.file('v4.FCStd','model bytes')
        report=self.file('validation.json','{}')
        with self.assertRaises(ValueError):
            record_validation({},model)
        with self.assertRaises(FileNotFoundError):
            record_validation({},model,self.root/'missing.json')
        with self.assertRaises(FileNotFoundError):
            record_validation({},self.root/'missing.FCStd',report)
        self.assertEqual(read_events(self.root/'journal'),[])

    def test_missing_fem_config_rejected(self):
        summary=self.file('summary.json','{}')
        with self.assertRaises(FileNotFoundError):
            record_fem('screening',{'solver':{'finished':True}},summary,self.root/'missing_config.json')
        self.assertEqual(read_events(self.root/'journal'),[])

    def test_validation_retry_count_and_hashes(self):
        model=self.file('v4.FCStd','model bytes')
        report=self.file('validation.json','{}')
        result={'solid':{'valid':True},'boolean_retries':2}
        event_path=record_validation(result,model,report)
        event=json.loads(event_path.read_text(encoding='utf-8'))
        self.assertEqual(event['data']['validation']['boolean_retries'],2)
        self.assertEqual({a['role'] for a in event['artifact_refs']},{'model','validation_report'})
        for a in event['artifact_refs']:
            self.assertEqual(a['sha256'],sha256(a['path']))
