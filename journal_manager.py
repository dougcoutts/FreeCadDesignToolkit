"""FreeCAD Engineering Toolkit — append-only journal event store (stdlib only)."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import uuid

TYPES = {'design_revision','engineering_run','visual_review','functional_review','ergonomic_review','decision','requirements_change','correction','status_change','observation'}
STATES = {'reported','proposed','pending','approved','rejected','deferred','completed','invalid','superseded','not_verified'}
PROVENANCE = {'measured','reported','inferred','owner_statement','proposed'}
ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def validate(event):
    errors=[]
    required=('schema_version','event_id','event_type','recorded_at','occurred_at','title','summary','status','provenance','source_refs','artifact_refs','related_event_ids','requirements_ids','design_revision','actor')
    for k in required:
        if k not in event: errors.append(f'missing {k}')
    if errors: return errors
    if event['schema_version'] != '1.0': errors.append('unsupported schema_version')
    if not isinstance(event['event_id'],str) or not ID_PATTERN.fullmatch(event['event_id']): errors.append('invalid event_id')
    if event['event_type'] not in TYPES: errors.append('invalid event_type')
    if event['status'] not in STATES: errors.append('invalid status')
    if event['provenance'] not in PROVENANCE: errors.append('invalid provenance')
    for k in ('title','summary','actor'):
        if not isinstance(event[k],str) or not event[k].strip(): errors.append(f'invalid {k}')
    for k in ('source_refs','artifact_refs','related_event_ids','requirements_ids'):
        if not isinstance(event[k],list): errors.append(f'{k} must be a list')
    for k in ('recorded_at','occurred_at'):
        if event[k] is not None:
            try:
                parsed=dt.datetime.fromisoformat(event[k].replace('Z','+00:00'))
                if parsed.tzinfo is None: errors.append(f'{k} requires timezone')
            except (TypeError,ValueError,AttributeError): errors.append(f'invalid {k}')
    if event['event_type'] in {'correction','status_change'} and not event['related_event_ids']:
        errors.append('correction/status_change must reference a prior event')
    for a in event['artifact_refs'] if isinstance(event['artifact_refs'],list) else []:
        if not isinstance(a,dict) or not isinstance(a.get('path'),str): errors.append('artifact requires path')
        if isinstance(a,dict) and a.get('sha256') is not None and not re.fullmatch(r'[0-9a-f]{64}',a['sha256']): errors.append('artifact invalid sha256')
    return errors


def read_events(root):
    root=pathlib.Path(root)
    events=[]
    for p in sorted((root/'events').glob('*.json')):
        e=json.loads(p.read_text(encoding='utf-8'))
        problems=validate(e)
        if problems: raise ValueError(f'{p}: {problems}')
        events.append(e)
    ids=[e['event_id'] for e in events]
    if len(ids)!=len(set(ids)): raise ValueError('duplicate event IDs')
    return events


def append_event(root,event):
    root=pathlib.Path(root)
    existing=read_events(root)
    known={e['event_id'] for e in existing}
    if not event.get('event_id'): event['event_id']=f'EVT-{uuid.uuid4().hex[:12]}'
    if not event.get('recorded_at'): event['recorded_at']=dt.datetime.now(dt.timezone.utc).isoformat()
    errors=validate(event)
    if errors: raise ValueError('; '.join(errors))
    if event['event_id'] in known: raise ValueError('event ID already exists')
    for ref in event['related_event_ids']:
        if ref not in known: raise ValueError(f'unknown related event {ref}')
    (root/'events').mkdir(parents=True,exist_ok=True)
    path=root/'events'/f"{event['event_id']}.json"
    # Exclusive creation prevents overwrite; immutable event files after creation.
    with open(path,'x',encoding='utf-8') as f:
        json.dump(event,f,indent=2,ensure_ascii=False)
        f.write('\n')
        f.flush(); os.fsync(f.fileno())
    return path


def current_status(events):
    """Derived current status, preserving the original event and all status changes."""
    state={e['event_id']:e['status'] for e in events}
    for e in events:
        if e['event_type']=='status_change':
            for target in e['related_event_ids']:
                if target in state: state[target]=e['status']
    return state


def render_markdown(events):
    state=current_status(events)
    out=['# Design Development Journal','',
         '> Generated view of append-only engineering records. Historical events remain unchanged.', '',
         '| Event | Type | Revision | Current status | Provenance |','|---|---|---|---|---|']
    for e in events:
        out.append('| '+ ' | '.join(str(x).replace('|','\\|').replace('\n',' ') for x in (e['event_id'],e['event_type'],e['design_revision'] or '—',state[e['event_id']],e['provenance']))+' |')
    out.append('')
    for e in events:
        out += [f"## {e['event_id']} — {e['title']}", '', e['summary'], '',
                f"- **Recorded:** {e['recorded_at']}",
                f"- **Occurred:** {e['occurred_at'] or 'Unknown (historical reconstruction)'}",
                f"- **Status:** {state[e['event_id']]} (original: {e['status']})",
                f"- **Provenance:** {e['provenance']}",
                f"- **Sources:** {', '.join(e['source_refs']) or 'None'}",
                f"- **Related events:** {', '.join(e['related_event_ids']) or 'None'}"]
        if e.get('data'): out += ['','**Structured findings**','', '```json',json.dumps(e['data'],indent=2), '```']
        out.append('')
    return '\n'.join(out)


def main():
    ap=argparse.ArgumentParser(description='Append-only engineering journal')
    sub=ap.add_subparsers(dest='command',required=True)
    a=sub.add_parser('append');a.add_argument('project');a.add_argument('event_json')
    v=sub.add_parser('validate');v.add_argument('project')
    r=sub.add_parser('render');r.add_argument('project');r.add_argument('output')
    h=sub.add_parser('hash');h.add_argument('file')
    args=ap.parse_args()
    if args.command=='append': print(append_event(args.project,json.loads(pathlib.Path(args.event_json).read_text(encoding='utf-8'))))
    elif args.command=='validate':
        ev=read_events(args.project); print(f'VALID: {len(ev)} event records')
    elif args.command=='render':
        pathlib.Path(args.output).write_text(render_markdown(read_events(args.project)),encoding='utf-8');print(args.output)
    elif args.command=='hash': print(sha256(args.file))

if __name__=='__main__':main()
