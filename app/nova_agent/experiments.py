"""Independent ACTION-only experiments. No patient classification or extra LLM."""
import copy
import json

from .context import reference_packet
from nova_retrieval.tokenize import tokenize

FLAGS = {'V0': (), 'V1': ('rag',), 'V2': ('interview',),
         'V3': ('communication',), 'V4': ('rag', 'interview', 'communication')}
FIELDS = ('id', 'kind', 'question', 'text', 'intent', 'consult_action_number')


def flags(strategy):
    if strategy not in FLAGS:
        raise ValueError('UNKNOWN_EXPERIMENT_STRATEGY')
    return FLAGS[strategy]


def action_prompt(baseline, strategy):
    enabled = flags(strategy)
    text = baseline
    if 'interview' in enabled:
        old = '현재 환자의 판단·처치를 바꿀 병력, 위험 신호와 필요한 신체진찰을 우선하세요. 횟수를 채우거나 모든 환자에게 같은 문진 목록을 적용하지 마세요.'
        new = '문진의 질문과 실제 답변을 대조해 판단에 중요한 미답변 부분만 확인하세요. 위험 확인이 우선이며, 문진으로 알 수 없는 중요한 소견은 EXAM으로 확인하세요. 증례에 무관한 목록을 채우지 마세요.'
        text = text.replace(old, new)
    if 'communication' in enabled:
        old = '환자의 걱정에 반응하고, 가능한 원인·불확실성·다음 계획·상황에 맞는 악화 시 대처를 필요한 시점에 실제 SAY(EXPLAIN)로 설명하세요. 설명 턴 수를 채우지 마세요.'
        new = '환자의 실제 질문·걱정·이해 곤란에 대응하세요. EXPLAIN 이력과 반응을 보고 아직 필요한 원인·불확실성·검사/치료/추적 이유·악화 증상과 행동 중 중요한 한 뜻을 SAY로 전하세요. 긴급 확인을 늦추거나 설명을 반복해 횟수를 채우지 마세요.'
        text = text.replace(old, new)
        text = text.replace('검사 계획은 최종 P에만 적고', '검사는 미실시 계획으로 P에 적고 필요하면 SAY로 설명하며')
    if 'interview' in enabled or 'communication' in enabled:
        text += '\ncurrent_patient_observations 표는 columns 순서의 원문 rows입니다. kind/intent는 수행 종류일 뿐 답변 충족·환자 이해의 증명이 아닙니다.'
    return text


def action_view(value, strategy):
    """Re-encode the SAME visible observations without summaries or new labels.

    Each fact occurs once. IDs/text/intent/order numbers stay intact. The field
    presence map preserves missing versus null for lossless regression checks.
    """
    enabled = flags(strategy)
    if not {'interview', 'communication'}.intersection(enabled):
        return value
    result = copy.deepcopy(value)
    facts = value['current_patient_observations']
    # Fail back to baseline representation if a future observation schema grows.
    if any(set(f) - set(FIELDS) for f in facts):
        return value
    initial = [f for f in facts if f['kind'] in ('opening', 'vitals')]
    asks = [f for f in facts if f['kind'] == 'patient_reply' and f.get('intent', 'ASK') == 'ASK']
    replies = [f for f in facts if f['kind'] == 'patient_reply']
    exams = [f for f in facts if f['kind'] == 'exam']
    explanations = [f for f in replies if f.get('intent') == 'EXPLAIN']
    priority = initial[:]
    if 'communication' in enabled:
        priority += replies[-1:] + list(reversed(explanations))
    if 'interview' in enabled:
        priority += asks[-1:] + list(reversed(exams))
    ordered, seen = [], set()
    for f in priority + facts:
        if f['id'] not in seen:
            ordered.append(f)
            seen.add(f['id'])
    result['current_patient_observations'] = {
        'columns': list(FIELDS), 'rows': [[f.get(k) for k in FIELDS] for f in ordered],
        'present': [[i for i, k in enumerate(FIELDS) if k in f] for f in ordered]}
    if 'communication' in enabled:
        # Remove the redundant speech list ONLY when all successful speeches
        # remain represented by intact observation/reaction pairs in this view.
        sent = value.get('doctor_explanations_already_sent', [])
        paired = [f['question'] for f in explanations]
        if sent == paired:
            result.pop('doctor_explanations_already_sent', None)
    return result


def clinical_packet(index, query, baseline, max_chars):
    """Add a complete, topical, actionable source only if baseline still fits.

    Never evict/truncate a baseline row to accommodate a heuristic priority.
    Lexical hints rank documents, not patient states or clinical correctness.
    Existing policy, source hash and complete-unit checks run in reference_packet.
    """
    audit = {'status': 'BASELINE_FALLBACK', 'added_ids': [], 'searches': 0}
    terms = set(tokenize(query, 'ko_bigram'))
    hints = ('문진', '신체', '진찰', '평가', '위험', '검사', '의뢰', '추적', '교육',
             'assessment', 'examination', 'referral', 'follow-up', 'counsel', 'red flag')
    def score(row):
        heading, text = str(row.get('unit_heading') or ''), row.get('text', '')
        if not isinstance(text, str) or row.get('case_id') or row.get('source_role') not in {
                'organizer_guideline', 'CLINICAL_REFERENCE', 'CLINICAL_GUIDELINE'}:
            return (0, 0)
        if not all(row.get(k) for k in ('unit_id', 'document_id', 'evidence_ids', 'unit_location', 'text_scope', 'source_sha256')):
            return (0, 0)
        if row.get('not_current_patient_facts') is not True:
            return (0, 0)
        topical = len(terms.intersection(tokenize(heading + ' ' + text, 'ko_bigram')))
        actionable = sum(h in (heading + ' ' + text).lower() for h in hints)
        return (actionable, topical) if topical >= 2 and actionable else (0, 0)
    ordered = sorted(baseline, key=score, reverse=True)
    if [r['unit_id'] for r in ordered] != [r['unit_id'] for r in baseline]:
        audit['status'] = 'BASELINE_UNITS_REORDERED'
    # A second complete-unit search was costly without adding evidence in the
    # public-opening projections. Reuse an already available topical clinical
    # unit instead; this is a retrieval sufficiency rule, not clinical adequacy.
    if any(score(row)[0] for row in baseline):
        audit['search_skipped'] = 'EXISTING_TOPICAL_CLINICAL_UNIT'
        return ordered, audit
    if len(baseline) >= 5 or max_chars - len(json.dumps(baseline, ensure_ascii=False)) < 512 or not query.strip():
        return ordered, audit
    suffix = ' 문진 신체진찰 위험 증상 검사 의뢰 추적 환자 교육'
    search_query = query + suffix if len(query) + len(suffix) <= 1800 else query
    try:
        audit['searches'] = 1
        candidates = reference_packet(index, search_query, max_chars, top_k=8)
    except (OSError, ValueError, KeyError, TypeError):
        audit['status'] = 'BASELINE_FALLBACK_SOURCE_ERROR'
        return baseline, audit
    seen = {r['unit_id'] for r in baseline}
    selected = []
    for row in candidates:
        actionable, topical = score(row)
        if not actionable or row['unit_id'] in seen:
            continue
        selected.append((actionable, topical, row))
    selected.sort(key=lambda item: (-item[0], -item[1]))
    additions = []
    for _, _, row in selected:
        if len(additions) + len(baseline) >= 5:
            break
        if row['unit_id'] not in seen and len(json.dumps(additions + [row] + baseline, ensure_ascii=False)) <= max_chars:
            additions.append(row)
            seen.add(row['unit_id'])
    if additions:
        audit.update(status='AUGMENTED_WITH_BASELINE_RETAINED', added_ids=[r['unit_id'] for r in additions])
        return additions + ordered, audit
    return ordered, audit
