# FreeCAD Design Toolkit

Source control for FreeCAD engineering automation, validation, and evidence journaling.

## Journal Manager

The Journal Manager v0.3 package includes a geometry validator, append-only event journal, evidence hashes, and regression tests. The v0.3 source includes opt-in journaling for the Shower Shelf scripts in `integrations/`.

## Workflow

- Keep CAD models, large generated artifacts, and project journals outside the source repository unless explicitly reviewed.
- Develop changes on branches and submit pull requests for review.
- Run Python unit tests and FreeCAD-specific integration checks before release.
- Never treat a completed validation event as engineering approval.

## Contents

- `journal_manager.py`, `event.schema.json`: original v0.1 event store and schema.
- `journal_integration.py`: standard-library bridge to record completed FEM analyses, saved CAD revisions, and geometry validation.
- `integrations/ShowerShelf_FEM_Screening.py`: emits one event after each newly completed run's summary is saved; skips `reuse_summary`.
- `integrations/ShowerShelf_FEM_Contact.py`: emits one event for each completed contact variant after summary is saved.
- `integrations/validate_v4_r2.py`: adds up to three attempts for intermittent `ValueError("Null shape")` in `_chord`, resets and records `boolean_retries` per validation, and supports `validate_and_journal(doc, ..., report_path=...)`.
- `integrations/ShowerShelf_build_script_V4.py`: adds `save_and_journal(doc, path)`; does **not** automatically save a model or claim approval.
- `tests/test_integration.py` and `tests/test_boolean_retry.py`: evidence-handling and isolated Boolean retry tests using synthetic inputs.

## Enabling journaling on Windows (PowerShell)

```powershell
$env:FREECAD_JOURNAL_PROJECT = 'C:\path\to\project\Journal'
```

The environment variable is optional. **Without it, existing FEM behavior is unchanged.** With it set, failures to write a journal event are raised rather than silently ignored. Geometry validation journaling now requires both an existing saved model and an existing report file; `validate_and_journal` writes the report before appending the event. Any supplied FEM or CAD evidence artifact must also exist. The directory will be created if needed.

For an existing script environment, put `journal_integration.py` and `journal_manager.py` in a directory on Python's `sys.path`, or retain the package layout shown here. The included scripts resolve the package parent automatically if used from `integrations/`.

Use the **integrated copies** in place of your existing scripts only after backing up and reviewing paths. Existing FEM configuration JSON is unchanged. Do not replace source scripts in an active FreeCAD session without testing.

For the CAD build script, use `save_and_journal(doc, absolute_model_path)` after building and checking the model. For geometry validation, call `validate_and_journal(doc, report_path=absolute_report_path)` instead of `validate(doc)`. The `report_path` argument is required when journaling is enabled. A plain `validate(doc)` remains available without journal side effects. The original entry point still calls `validate(doc)` and does not journal by default.

## Provenance and limitations

- Events are labeled `reported`, not independently `measured` or `approved`. The bridge hashes required and supplied evidence files (SHA-256) and captures selected numerical and configuration fields.
- FEM run artifacts are **referenced**, not copied. For durable evidence, preserve the original input/output files separately; hashes alone do not prevent edits/deletion.
- A completed solver run does not establish mesh convergence, contact-model validity, structural acceptance, or requirements compliance.
- The bridge writes after the summary is produced. If event creation fails, the FEM results may already exist; rerunning can create a second record. There is no cross-process transaction or project-level lock.
- Concurrent writers remain unsupported beyond exclusive event filename creation. Avoid multiple agents writing simultaneously to the same journal directory.
- Contact summaries may contain variant-specific names; source summary and config are always hashed, but this first bridge does not comprehensively map every variant-specific solver output file.
- Existing `validate` and `build_v4` entry points are unchanged; explicit wrappers are provided to avoid silently altering CAD/save behavior.
- FreeCAD/Gmsh/CalculiX are required for live geometry and FEM checks as applicable. The Python suite exercises the event bridge with synthetic files and tests Boolean retries with mocks. Run live geometry validation and FEM jobs in your installed FreeCAD environment before production use.

## Tests

Run the unit suite from the repository root with standard Python. Use the CLI examples below to validate or render an existing project journal.

```powershell
python -m unittest discover -s tests -v
python journal_manager.py validate 'C:\path\to\project\Journal'
python journal_manager.py render 'C:\path\to\project\Journal' journal.md
```

## Next development steps

1. Run a controlled FreeCAD geometry validation and one FEM job using the integrated scripts.
2. Add robust solver-evidence capture for each contact variant and an event-to-requirement mapping.
3. Add safe multi-agent write coordination and rich illustrated Word journal generation.

## v0.3 changes and compatibility

- Boolean retry handling is limited to `_chord` calls that raise exactly `ValueError("Null shape")`; after three failed attempts the exception propagates. Other exceptions are not retried.
- The returned validation dictionary includes `boolean_retries`; the count is reset for each full `validate` call. A manual `_chord` call increments the current module counter independently.
- `record_validation` now requires **both** `model_path` and `report_path` when journaling is enabled. Missing files raise before any event is appended. This is a deliberate API tightening from v0.2.
- `_record` rejects any nonempty supplied artifact path that does not exist, including FEM supplemental evidence; omitted optional artifacts remain optional.
- A SHA-256 reference proves equality at verification time but does not archive or freeze a referenced file. Preserve referenced artifacts.
- No existing append-only event files are modified. Do not overwrite the installed v0.2 package until validating the updated package in FreeCAD.
