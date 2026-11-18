"""Opt-in bridge for ShowerShelf scripts to the append-only Journal Manager.

Importable without FreeCAD, NumPy, or a solver. Interactive CAD recording requires
FreeCAD GUI. Recording is a no-op unless FREECAD_JOURNAL_PROJECT is set.
Errors are raised when journaling is enabled so successful analysis cannot silently
appear to have been recorded when it was not.
"""
from __future__ import annotations
import datetime as dt
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
    return append_event(project, _event(kind, title, summary, revision, source_files, refs, data, actor))

def _event(kind, title, summary, revision, source_files, refs, data, actor='FreeCAD Python integration'):
    return {
        'schema_version': '1.0', 'event_id': 'AUTO-' + uuid.uuid4().hex,
        'event_type': kind, 'recorded_at': _utc(), 'occurred_at': _utc(),
        'title': title, 'summary': summary, 'status': 'completed',
        'provenance': 'reported', 'source_refs': [str(Path(p).resolve()) for p in source_files if p],
        'artifact_refs': refs, 'related_event_ids': [], 'requirements_ids': [],
        'design_revision': revision, 'actor': actor, 'data': data
    }

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

def verify_saved_model(doc, expected_sha256=None, expected_path=None):
    """Verify the saved FCStd evidence and GUI unsaved-change state.

    FreeCAD App.Document has no Modified attribute in FreeCAD 1.1.4.
    Gui.getDocument(doc.Name).Modified is the observed unsaved-change flag.
    Fail closed if the matching GUI document cannot be checked.
    """
    model_path = getattr(doc, 'FileName', '')
    if not model_path:
        raise ValueError('Save FreeCAD document before journaling validation')
    doc_name = getattr(doc, 'Name', None)
    if not doc_name:
        raise ValueError('Cannot identify FreeCAD document for GUI state check')
    try:
        import FreeCADGui as Gui
        gui_doc = Gui.getDocument(doc_name)
        if gui_doc is None:
            raise ValueError('No matching FreeCAD GUI document for saved-model verification')
        modified = bool(gui_doc.Modified)
    except (ImportError, AttributeError) as exc:
        raise ValueError('Cannot verify FreeCAD GUI document Modified state') from exc
    if modified:
        raise ValueError('FreeCAD document has unsaved changes; save before journaling')
    path = Path(model_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f'Saved FreeCAD model not found: {path}')
    if expected_path is not None and str(path) != str(Path(expected_path).resolve()):
        raise ValueError('FreeCAD document refers to a different model after validation')
    digest = sha256(path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError('Saved FreeCAD model changed during validation')
    return str(path), digest


def record_validation(result, model_path, report_path=None):
    if not os.environ.get(ENV): return None
    if not model_path or not report_path:
        raise ValueError('Geometry journaling requires model_path and report_path')
    artifacts=[('model',model_path),('validation_report',report_path)]
    return _record('observation',f'Geometry validation: {Path(model_path).stem}',
        'Geometry validation completed; inspect recorded checks before asserting compliance.',
        Path(model_path).stem,[model_path,report_path],artifacts,{'validation':result})

def _cad_event(model_ref, script_path, revision):
    if not script_path:
        raise ValueError('CAD journaling requires build-script evidence')
    script_ref = _artifact(script_path, 'build_script')
    model_stem = Path(model_ref['path']).stem
    return _event('design_revision', f'CAD revision saved: {model_stem}',
        'Saved CAD artifact captured; no visual or engineering approval implied.',
        revision or model_stem, [script_ref['path']], [model_ref, script_ref],
        {'model_sha256': model_ref['sha256']})

def record_cad(doc, model_path, script_path, revision=None):
    """Record a saved model after verifying its live FreeCAD GUI document."""
    project = os.environ.get(ENV)
    if not project:
        return None
    if not model_path:
        raise ValueError('CAD journaling requires the saved model path')
    path, digest = verify_saved_model(doc, expected_path=model_path)
    event = _cad_event({'path': path, 'sha256': digest, 'role': 'model'}, script_path, revision)
    verify_saved_model(doc, expected_sha256=digest, expected_path=path)
    return append_event(project, event)

def record_cad_artifact(model_path, script_path, revision=None):
    """Record model and build-script files generated outside the FreeCAD GUI."""
    project = os.environ.get(ENV)
    if not project:
        return None
    event = _cad_event(_artifact(model_path, 'model'), script_path, revision)
    return append_event(project, event)
