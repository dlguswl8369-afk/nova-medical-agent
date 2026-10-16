"""Source-linked action views, not inferred clinical states or output contracts.

Independent implementation: no external agent code, summarizer, or dependency.
All clinical interpretation remains in the existing single Doctor action call.
RECORD continues to receive the v3.5 context, not these action-only views.
"""
import json

from .context import visible_facts
from .prompts import STEP

STRATEGIES = ('baseline', 'A', 'B', 'C')

POLICIES = {
    'A': '''누적 관찰과 latest_observation_ids로 중요한 감별을 갱신하고, 새 위험 신호는 기존 가설보다 먼저 확인하세요. 진단 확률 수치나 감별 목록을 출력할 필요는 없습니다.
각 가설을 지지하거나 반박하는 환자 원문을 대조하고, 답에 따라 진단·처치가 달라질 미확인 정보 하나를 선택하세요. 말로 확인할 정보는 ASK, 실제 신체 소견이 필요하면 구체적인 EXAM을 선택하세요.
history_reply_ids의 질문을 했다는 이유만으로 답변 완료로 간주하지 마세요. 확인된 답은 재질문하지 않고 중요한 미답변만 보완하세요. reference_unit_ids의 자료는 환자 관찰과 별개이며 가설 비교의 참고일 뿐입니다.
더 확인해도 현재 결정이 달라지지 않으면 필요한 설명 후 DONE을 고려하세요. 불확실성을 모두 없애려 질문하거나 가설 확신만으로 위험 확인을 생략하지 마세요.''',
    'B': '''observed_exam_ids와 history_reply_ids의 실제 결과로 남은 불확실성을 확인하세요. 다음 ASK/EXAM이 처치·의뢰·추적 결정을 바꾸는지 비교해 필요한 하나를 선택하세요.
검사가 필요하면 어떤 불확실성을 확인할지, 결과에 따라 다음 조치가 달라질지 생각하세요. TEST는 실행하지 않으며 필요한 검사 목적·의뢰·추적·악화 시 대처는 현재 관찰에 맞춰 설명하세요. 미실시 검사를 정상으로 가정하지 마세요.
delivered_explanation_reply_ids는 설명과 반응의 원문 위치이며 계획 완료나 이해 완료가 아닙니다. P에 쓸 계획과 이미 SAY로 전달한 내용을 구분하고, 필요한 안내만 증상·행동과 연결하세요.
현재 필요한 확인·안내가 끝나면 DONE을 고려하세요. 확진을 위한 검사를 여기서 대신하거나 횟수를 채우지 마세요.''',
    'C': '''latest_patient_reply_id와 dialogue_links의 질문/설명·환자 답변을 함께 읽으세요. 실제 걱정·요청·질문에는 아는 범위에서 답하고, 새로운 위험 신호가 있으면 안전 확인을 우선하세요.
복합 질문의 답변을 항목 전체로 확대하지 마세요. 이미 확인한 내용은 생략하고 진료 결정에 필요한 미답변만 하나씩 확인하세요. 모르는 항목을 끝없이 재질문하지 마세요.
문진·진찰·계획의 목적은 필요할 때 쉽게 설명하고, 현재 필요한 검사·추적·악화 시 대처를 실제 SAY로 전할지 판단하세요. P 작성은 전달이 아니며 단순 수긍은 이해 증명이 아닙니다.
설명 뒤 새 질문·이해 곤란이 있으면 그 부분에 대응하세요. 같은 뜻의 설명을 반복하거나 고정 설명·이해 확인 횟수를 채우지 말고 필요한 임상 확인과 DONE을 함께 고려하세요.''',
}


def validate_strategy(strategy):
    if strategy not in STRATEGIES:
        raise ValueError('INVALID_CLINICAL_STRATEGY')
    return strategy


def action_prompt(strategy):
    validate_strategy(strategy)
    if strategy == 'baseline':
        return STEP
    # Shared correction distinguishes prohibited execution from allowed speech.
    # No change to prompts.RECORD or the v3.5 baseline ablation.
    base = STEP.replace('검사 계획은 최종 P에만 적고',
                        '검사 계획은 미실시 계획으로 P에 적고 필요하면 SAY로 설명하며')
    return base + '\n전략별 관찰 안내는 ID 색인이지 임상 판정이나 완료 상태가 아닙니다. 원문을 확인하고 기존 단일 행동 JSON만 출력하세요.\n' + POLICIES[strategy]


def action_facts(facts, strategy, max_chars):
    """Pack whole raw observations under the existing cap; never infer polarity.

    Under pressure, newest feedback precedes strategy-specific evidence. Initial
    observations remain protected. RECORD packing is intentionally unchanged.
    """
    baseline = visible_facts(facts, max_chars)
    if strategy == 'baseline':
        return baseline
    validate_strategy(strategy)
    initial = [f for f in facts if f['kind'] in ('opening', 'vitals')]
    recent = [f for f in reversed(facts) if f['kind'] not in ('opening', 'vitals')]
    if strategy == 'A':
        priority = recent[:4]
    elif strategy == 'B':
        priority = [f for f in recent if f['kind'] == 'exam']
    else:
        priority = [f for f in recent if f['kind'] == 'patient_reply'][:3]
        priority += [f for f in recent if f['kind'] == 'exam'][:1]
    selected = list(initial)
    seen = {f['id'] for f in selected}
    for f in recent[:1] + priority + baseline + recent:
        if f['id'] not in seen and len(json.dumps(selected + [f], ensure_ascii=False)) <= max_chars:
            selected.append(f)
            seen.add(f['id'])
    return sorted(selected, key=lambda f: int(f['id'][1:]))


def decision_view(facts, refs, strategy):
    """IDs link back to the one raw observation store, without new fact claims."""
    validate_strategy(strategy)
    ids = lambda kind: [f['id'] for f in facts if f['kind'] == kind]
    replies = [f for f in facts if f['kind'] == 'patient_reply']
    view = {'strategy': strategy,
            'latest_observation_ids': [f['id'] for f in facts[-2:]],
            'history_reply_ids': [f['id'] for f in replies if f.get('intent') != 'EXPLAIN'],
            'observed_exam_ids': ids('vitals') + ids('exam'),
            'reference_unit_ids': [r['unit_id'] for r in refs]}
    if strategy == 'B':
        view.update(executed_test_ids=[],
                    delivered_explanation_reply_ids=[f['id'] for f in replies if f.get('intent') == 'EXPLAIN'])
    elif strategy == 'C':
        view.update(latest_patient_reply_id=replies[-1]['id'] if replies else None,
                    dialogue_links=[{'observation_id': f['id'],
                                     'preceding_doctor_intent': f.get('intent', 'ASK')}
                                    for f in replies])
    return view
