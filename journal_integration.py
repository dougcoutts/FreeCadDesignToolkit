"""Opt-in bridge for ShowerShelf scripts to the append-only Journal Manager.

No FreeCAD, NumPy, or solver dependency. No-op unless FREECAD_JOURNAL_PROJECT is set.
Errors are raised when journaling is enabled so successful analysis cannot silently
appear to have been recorded when it was not.
"""
from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
import uuid
from journal_manager import append_event, sha256

ENV = 'FREECAD_JOURNAL_PROJECT'

def _utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def _artifact(path, role):
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f'Missing journal evidence ({role}): {p}')
    return {'path': str(p), 'sha256': sha256(p), 'role': role}

def _record(kind, title, summary, revision, source_files, artifacts, data, actor='FreeCAD Python integration'):
    project = os.environ.get(ENV)
    if not project:
        return None
    refs = []
    for role, path in artifacts:
        if path:
            refs.append(_artifact(path, role))
    event = {
        'schema_version': '1.0', 'event_id': 'AUTO-' + uuid.uuid4().hex,
        'event_type': kind, 'recorded_at': _utc(), 'occurred_at': _utc(),
        'title': title, 'summary': summary, 'status': 'completed',
        'provenance': 'reported', 'source_refs': [str(Path(p).resolve()) for p in source_files if p],
        'artifact_refs': refs, 'related_event_ids': [], 'requirements_ids': [],
        'design_revision': revision, 'actor': actor, 'data': data
    }
    return append_event(project, event)

def record_fem(kind, summary, summary_path, config_path, model_path=None, run_dir=None):
    if not os.environ.get(ENV): return None
    if kind not in ('screening', 'contact'): raise ValueError('unknown FEM kind')
    if not Path(summary_path).is_file(): raise FileNotFoundError(summary_path)
    tag = summary.get('model', {}).get('variant') or summary.get('model', {}).get('tag') or Path(summary_path).stem
    solver = summary.get('solver', {})
    if solver.get('finished') is False or solver.get('final_finished') is False:
        raise ValueError('refusing to record unfinished solver run')
    artifacts = [('summary',summary_path),('config',config_path),('model',model_path)]
    if run_dir:
        d=Path(run_dir)
        for ext in ('.inp','.dat','.sta','.log','.frd'):
            artifacts.append(('solver'+ext,d/(tag+ext)))
    data={'analysis_kind':kind, 'model':summary.get('model'), 'mesh':summary.get('mesh'),
          'loads':summary.get('loads'), 'bc':summary.get('bc'), 'material':summary.get('material'),
          'solver':summary.get('solver'), 'equilibrium':summary.get('equilibrium'),
          'max_down_disp_mm':summary.get('max_down_disp_mm'),
          'max_vonMises_MPa_excl_constrained':summary.get('max_vonMises_MPa_excl_constrained'),
          'summary_sha256':sha256(summary_path)}
    return _record('engineering_run',f'{kind.capitalize()} FEM run: {tag}',
        'Completed FEM calculation; results are recorded, not automatically approved as compliant.',
        tag,[config_path,summary_path],artifacts,data)

def record_validation(result, model_path, report_path=None):
    if not os.environ.get(ENV): return None
    if not model_path or not report_path:
        raise ValueError('Geometry journaling requires model_path and report_path')
    artifacts=[('model',model_path),('validation_report',report_path)]
    return _record('observation',f'Geometry validation: {Path(model_path).stem}',
        'Geometry validation completed; inspect recorded checks before asserting compliance.',
        Path(model_path).stem,[model_path,report_path],artifacts,{'validation':result})

def record_cad(model_path, script_path, revision=None):
    if not os.environ.get(ENV): return None
    if not Path(model_path).is_file():
        raise FileNotFoundError('Save the FreeCAD model before recording it: '+str(model_path))
    return _record('design_revision',f'CAD revision saved: {Path(model_path).stem}',
        'Saved CAD artifact captured; no visual or engineering approval implied.',
        revision or Path(model_path).stem,[script_path], [('model',model_path),('build_script',script_path)],
        {'model_sha256':sha256(model_path)})
