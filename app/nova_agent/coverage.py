"""Observed care navigation and one-step Doctor intent, never clinical labels.

No regex symptom classification, clinical completeness score, or DONE gate.
Original observations remain authoritative; this module only links their IDs.
"""
import json


def action_facts(facts, baseline_visible, max_chars):
    """Keep latest patient reaction and exam intact within the existing fact cap.

    Only ACTION uses this ordering. RECORD and retrieval retain v3.5 selection.
    No text is cut, interpreted as negative, or promoted from a Doctor plan.
    """
    initial = [f for f in facts if f['kind'] in ('opening', 'vitals')]
    latest = []
    for kind in ('patient_reply', 'exam'):
        item = next((f for f in reversed(facts) if f['kind'] == kind), None)
        if item is not None:
            latest.append(item)
    selected = list(initial)
    selected_ids = {f['id'] for f in selected}
    for item in latest + baseline_visible + list(reversed(facts)):
        if item['id'] not in selected_ids and len(json.dumps(selected + [item], ensure_ascii=False)) <= max_chars:
            selected.append(item)
            selected_ids.add(item['id'])
    # Retain original chronology and original objects/strings, not summaries.
    return [f for f in facts if f['id'] in selected_ids]


def next_focus(obj):
    """An optional planning note cannot invalidate an otherwise valid action."""
    text = obj.get('next_focus')
    if isinstance(text, str) and 0 < len(text.strip()) <= 240:
        return text.strip()
    return None


def coverage_context(visible, all_facts, carry):
    """Distinguish supplied findings, actions, answers and delivered speech.

    An ID under asked_reply_ids means a question and response exist, NOT that
    every component was answered. Partial/unknown answers require reading the
    untouched pair. No clinical gaps are manufactured from absent categories.
    """
    replies = [f for f in visible if f['kind'] == 'patient_reply']
    selected = {f['id'] for f in visible}
    patient = [f for f in all_facts if f['kind'] in ('opening', 'patient_reply')]
    latest = patient[-1]['id'] if patient else None
    # Only acknowledged actions produce facts in Run.execute.
    view = {
        'opening_ids': [f['id'] for f in visible if f['kind'] == 'opening'],
        'supplied_vital_ids': [f['id'] for f in visible if f['kind'] == 'vitals'],
        'asked_reply_ids': [f['id'] for f in replies if f.get('intent', 'ASK') == 'ASK'],
        'performed_exam_ids': [f['id'] for f in visible if f['kind'] == 'exam'],
        'delivered_explanation_reply_ids': [f['id'] for f in replies if f.get('intent') == 'EXPLAIN'],
        'empty_reply_ids': [f['id'] for f in replies if not f['text'].strip()],
        'latest_patient_statement_id': latest if latest in selected else None,
        'omitted_observation_ids': [f['id'] for f in all_facts if f['id'] not in selected],
        'executed_test_ids': [],
    }
    if carry:
        # Pending intent is neither observed evidence nor a task to force-complete.
        view['previous_doctor_intent_not_observation'] = dict(carry)
    return view
