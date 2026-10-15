"""Render S/O from observations, never from generated clinical prose."""
import json
from nova_sdk import empty_record, RECORD_FIELDS


def clean_string(value, limit=1200):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("INVALID_RECORD_STRING")
    return value.strip()


def format_fact(f):
    if f.get("question"):
        if f['kind'] == 'exam':
            turn = f" (진료 행동 {f['consult_action_number']}회차)" if 'consult_action_number' in f else ''
            return f"[{f['id']}]{turn} 시행한 진찰: {f['question']} / 관찰 결과: {f['text']}"
        return f"[{f['id']}] 문진 질문: {f['question']} / 환자 답변: {f['text']}"
    return f"[{f['id']}] {f['text']}"


def render_record(plan, facts, explanations):
    if not isinstance(plan, dict):
        raise ValueError("INVALID_RECORD_OBJECT")
    by_id = {f["id"]: f for f in facts}
    diagnosis = clean_string(plan.get("diagnosis"), 120)
    if not diagnosis or any(x in diagnosis for x in ["\n", ";", " 또는 ", " or ", " / "]):
        raise ValueError("ONE_DIAGNOSIS_REQUIRED")

    def refs(value, allowed=None):
        if not isinstance(value, list) or len(value) > 52 or any(not isinstance(x, str) or x not in by_id for x in value):
            raise ValueError("UNKNOWN_OBSERVATION_ID")
        selected = [by_id[x] for x in dict.fromkeys(value)]
        if allowed and any(f["kind"] not in allowed for f in selected):
            raise ValueError("OBSERVATION_SOURCE_MISMATCH")
        return selected

    basis = refs(plan.get("diagnosis_basis"))
    if not basis:
        raise ValueError("DIAGNOSIS_BASIS_REQUIRED")
    note = empty_record()
    mapping = plan.get("source_refs")
    if not isinstance(mapping, dict) or set(mapping) != {"S", "O"}:
        raise ValueError("INVALID_SOURCE_REFS")
    for section in ("S", "O"):
        if not isinstance(mapping[section], dict) or set(mapping[section]) != set(RECORD_FIELDS[section]):
            raise ValueError("INVALID_SOURCE_FIELDS")
        for field in RECORD_FIELDS[section]:
            chosen = refs(mapping[section][field], {"opening", "patient_reply"} if section == "S" else {"vitals", "exam"})
            if section == "O" and field == "tests" and chosen:
                raise ValueError("PRELIMINARY_TEST_RESULTS_FORBIDDEN")
            note[section][field] = "\n".join(format_fact(f) for f in chosen)
    # Retain supplied opening and vitals even if the model leaves slots empty.
    note['S']['cc'] = note['S']['cc'] or '\n'.join(format_fact(f) for f in facts if f['kind'] == 'opening')
    note['O']['exam'] = '\n'.join(dict.fromkeys([*(format_fact(f) for f in facts if f['kind'] == 'vitals'), note['O']['exam']])).strip()
    note['O']['tests'] = ''
    note['A']['evidence'] = '[추정 주진단] ' + diagnosis + '\n[현재 환자 근거]\n' + '\n'.join(format_fact(f) for f in basis)
    for key, field in [('assessment', 'evidence'), ('differential', 'differential')]:
        entries = plan.get(key, [])
        if not isinstance(entries, list) or len(entries) > 8:
            raise ValueError('INVALID_ASSESSMENT')
        lines = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError('INVALID_ASSESSMENT')
            cited = refs(entry.get('fact_ids'))
            if not cited:
                raise ValueError('ASSESSMENT_BASIS_REQUIRED')
            lines.append('[추론/미확정] ' + clean_string(entry.get('text')) + ' (근거: ' + ', '.join(f['id'] for f in cited) + ')')
        note['A'][field] += ('\n' if note['A'][field] and lines else '') + '\n'.join(lines)
    plans = plan.get('plans')
    if not isinstance(plans, dict) or set(plans) != set(RECORD_FIELDS['P']):
        raise ValueError('INVALID_PLAN_FIELDS')
    for field in RECORD_FIELDS['P']:
        value = clean_string(plans[field])
        note['P'][field] = ('[계획; 시행 여부 미확인] ' + value) if value else ''
    if explanations:
        note['P']['education'] = '[실제 SAY 설명]\n' + '\n'.join(explanations) + '\n' + note['P']['education']
    if len(json.dumps(note, ensure_ascii=False).encode('utf-8')) > 100000 or len(diagnosis.encode('utf-8')) > 500:
        raise ValueError('RECORD_BYTE_BUDGET')
    return note, diagnosis


def fallback_record(facts, explanations):
    note = empty_record()
    note['S']['cc'] = '\n'.join(format_fact(f) for f in facts if f['kind'] == 'opening')
    note['S']['hpi'] = '\n'.join(format_fact(f) for f in facts if f['kind'] == 'patient_reply')
    note['O']['exam'] = '\n'.join(format_fact(f) for f in facts if f['kind'] in {'vitals', 'exam'})
    note['A']['evidence'] = '진단 미정: Doctor 응답 오류 또는 정보 부족. 확인된 원문만 보존함.'
    note['P']['education'] = '[실제 SAY 설명]\n' + '\n'.join(explanations) if explanations else ''
    return note, '진단 미정'
