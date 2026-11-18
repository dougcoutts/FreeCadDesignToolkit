import json, os, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from journal_integration import record_fem, record_cad, record_validation, ENV
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
    def test_saved_cad_and_validation(self):
        p=self.file('v4.FCStd','test bytes')
        script=self.file('build.py','pass')
        record_cad(p,script,'V4')
        report=self.file('validation.json','{"solid": {"valid": true}}')
        record_validation({'solid':{'valid':True}, 'boolean_retries':0},p,report)
        self.assertEqual({e['event_type'] for e in read_events(self.root/'journal')},{'design_revision','observation'})
    def test_disabled_is_noop(self):
        os.environ.pop(ENV,None)
        self.assertIsNone(record_cad('missing.FCStd','missing.py'))

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
