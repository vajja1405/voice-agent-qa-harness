"""Pure validation and selection helpers; no credentials or network required."""
import json
from datetime import datetime, timezone


def parse_grade(raw):
    text = raw.strip()
    if text.startswith('```'):
        lines = text.splitlines()
        if lines[-1].strip() != '```':
            raise ValueError('Unclosed judge JSON fence')
        text = '\n'.join(lines[1:-1])
    return validate_grade(json.loads(text))


def validate_grade(row):
    if not isinstance(row, dict):
        raise ValueError('Judge must return an object')
    for key in ('task_completed', 'contained'):
        if type(row.get(key)) is not bool:
            raise ValueError(f'{key} must be boolean')
    for key in ('rule_conformance_ok', 'memory_ok', 'safety_ok'):
        if key not in row or (row[key] is not None and type(row[key]) is not bool):
            raise ValueError(f'{key} must be boolean or null')
    if type(row.get('conversation_quality')) is not int or not 1 <= row['conversation_quality'] <= 5:
        raise ValueError('conversation_quality must be an integer from 1 to 5')
    if not isinstance(row.get('summary'), str) or not row['summary'].strip():
        raise ValueError('summary must be nonempty text')
    if not isinstance(row.get('bugs'), list):
        raise ValueError('bugs must be a list')
    for bug in row['bugs']:
        if not isinstance(bug, dict) or bug.get('severity') not in {'Critical','High','Medium','Low'}:
            raise ValueError('Invalid bug severity')
        if any(not isinstance(bug.get(k), str) or not bug[k].strip()
               for k in ('title','evidence_quote','why_it_matters')):
            raise ValueError('Every bug needs title, evidence_quote and why_it_matters')
    return row


def latest_calls(calls):
    """Select each scenario's latest capture; reject mixed timestamp conventions."""
    selected, awareness = {}, set()
    for call in calls:
        if not isinstance(call, dict) or not isinstance(call.get('scenario'), str) or not call['scenario']:
            raise ValueError('Transcript requires a scenario')
        if not call.get('turns') or not all(isinstance(t, dict) and t.get('speaker') in {'agent','patient'}
              and isinstance(t.get('text'), str) and t['text'].strip() for t in call['turns']):
            raise ValueError(f"{call['scenario']}: invalid or empty turns")
        for key in ('category','what_to_check','started_at'):
            if not isinstance(call.get(key), str) or not call[key].strip():
                raise ValueError(f'{key} is required')
        stamp = datetime.fromisoformat(call['started_at'])
        awareness.add(stamp.tzinfo is not None)
        if len(awareness) > 1:
            raise ValueError('Mixed timezone-aware and naive timestamps; use a consistent capture directory')
        stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
        key = call['scenario']
        if key in selected and stamp == selected[key][0]:
            raise ValueError(f'{key}: ambiguous duplicate timestamp')
        if key not in selected or stamp > selected[key][0]:
            selected[key] = (stamp, call)
    return [selected[k][1] for k in sorted(selected)]


def scorecard(graded, synthetic=False):
    return {c['scenario']: {
        'contained': r['contained'], 'task_completed': r['task_completed'],
        'safety_ok': r['safety_ok'], 'quality': r['conversation_quality'],
        'n_bugs': len(r['bugs']), 'synthetic': synthetic,
        'source_call_sid': c.get('call_sid'), 'source_started_at': c['started_at'],
    } for c, r in graded}
