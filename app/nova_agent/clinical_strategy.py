"""Small, session-local decision interventions; proposals are never observations."""
import unicodedata

from .diagnostics import parse_action

FEATURES = {'BASELINE': (), 'H1': ('planner',), 'H2': ('examination',),
            'H3': ('audit',), 'H4': ('planner', 'examination', 'audit')}

PLAN = '''CLINICAL_PLANNER_NOT_PATIENT_FACTS
현재 관찰 원문과 ID만 환자 사실입니다. 참고자료는 별도 근거이며 계획은 수행 사실이 아닙니다.
이 환자에서 진단·처치를 구분할 중요한 미확인 병력·양성/음성 확인, 필요한 신체진찰, 설명·검사/의뢰/추적·안전 안내를 간결하게 계획하세요. 이미 확인한 것·부분 답변·모름을 구분하세요.
고정 문진표나 고정 진단을 만들지 말고, 새 답변이 다르면 버릴 수 있는 가설로 두세요. 위험이 드러났으면 계획보다 그 확인/대응을 다음 행동으로 선택하세요.
JSON {"plan":"관찰 ID에 근거한 환자별 잠정 계획, 1600자 이내", "next_action":{"action":"SAY","intent":"ASK","content":"질문 하나"}}
next_action은 선택 사항이며 SAY(ASK/EXPLAIN), EXAM, DONE 중 하나입니다. SAY/EXAM은 NFC 30자 이하, EXAM은 구체적인 신체진찰 동작 하나입니다. TEST·검사결과 생성은 금지합니다.
설명할 내용은 아직 전송하지 않은 제안이며 환자 이해의 증명이 아닙니다. 불필요한 추가 질문은 제안하지 마세요.'''

AUDIT = '''PRE_DONE_AUDIT_NOT_PATIENT_FACTS
현재 관찰·질문/답변 원문과 실제 설명 전달을 처음부터 대조하는 종료 검토입니다. 기존 잠정 계획이나 다른 호출의 추론을 사실로 사용하지 마세요.
진단·처치를 바꿀 미확인 병력, 필요한 진찰 누락, 부분 답변의 음성 확대, 직접 질문 미응답, 실제 전달하지 않은 중요한 설명·검사/추적/악화 시 대응이 있는지 검토하세요.
충분하거나 추가 행동의 가치가 낮으면 {"action":"DONE"}을 그대로 출력하세요. 목록을 채우거나 무조건 추가 행동을 만들지 마세요.
중요한 누락이 있으면 지금 가장 필요한 행동 하나만 JSON으로 제안하세요: {"action":"SAY","intent":"ASK 또는 EXPLAIN","content":"30자 이하 한 뜻"} 또는 {"action":"EXAM","content":"구체적인 신체진찰 동작 하나"}.
위험 확인/대응을 설명이나 일반 문진보다 우선하세요. 실제 수행한 진찰과 계획을 구별하세요. TEST는 금지이며 미시행 검사 결과를 만들지 마세요. 단순 동의나 전송 성공을 이해 완료로 보지 마세요.
관찰되지 않은 사실을 새로 만들지 말고, 동일 행동을 불필요하게 반복하지 마세요.'''


def features(strategy):
    if strategy not in FEATURES:
        raise ValueError('UNKNOWN_CLINICAL_STRATEGY')
    return FEATURES[strategy]


def call_settings(strategy, purpose, seconds_left):
    enabled = features(strategy)
    if purpose == 'PLAN' and 'planner' in enabled:
        return 3072, 'medium'
    if purpose == 'AUDIT' and 'audit' in enabled:
        # seconds_left is measured after the unchanged final time margin.
        return (4096, 'high') if strategy == 'H4' and seconds_left > 300 else (3072, 'medium')
    raise ValueError('AUXILIARY_PURPOSE_NOT_ENABLED')


def step_prompt(baseline, strategy):
    enabled = features(strategy)
    if not enabled:
        return baseline
    text = baseline.replace('검사 계획은 최종 P에만 적고', '검사는 미실시 계획으로 P에 적고 필요하면 SAY로 설명하며')
    if 'planner' in enabled:
        text += '\n초기 위험 확인을 먼저 수행하세요. 현재 답변까지 본 뒤 급한 확인/조치를 늦추지 않고 계획 검토가 도움이 되면 행동 JSON에 planning_ready:true를 선택적으로 붙이세요. 급한 행동은 urgent:true로 표시하세요. 계획은 가설/미실시 제안이며 새 사실과 다르면 따르지 마세요. 필요하면 plan_update 문자열(1600자 이내)로 같은 호출에서 수정할 수 있습니다.'
    if 'examination' in enabled:
        text += '\n다음 문진과 신체진찰 중 어느 쪽이 지금 판단을 더 바꾸는지 비교하세요. 문진 대신 진찰이 유용하면 SAY/ASK JSON에 prefer_exam:true와 exam_option:{"content":"구체적 진찰 하나","basis_ids":["F0"],"decision":"바뀌는 판단"}을 함께 제안할 수 있습니다. 급한 질문/안내는 urgent:true로 유지하세요. 고정 진찰 횟수는 없으며 필요한 질문·부분 답변 확인을 생략하지 마세요. 이전 거절 진찰은 구체화하거나 다른 유효 행동을 선택하세요.'
    text += '\nclinical_plan_not_patient_facts와 last_exam_failure_not_patient_facts는 계획·실패 이력입니다. 수행 결과나 환자 사실이 아닙니다. 설명은 필요한 시점에 실제 SAY(EXPLAIN)로 전달하고 최종 P와 구분하세요.'
    return text


def plan_text(value):
    if not isinstance(value, str):
        return None
    value = unicodedata.normalize('NFC', value).strip()
    return value if 0 < len(value) <= 1600 else None


def audit_action(value, blocked):
    # Explicit reviewer vocabulary only; never reinterpret TEST as EXAM.
    if value.get('action') in ('ASK', 'EXPLAIN'):
        value = dict(value, action='SAY', intent=value['action'])
    return parse_action(value, blocked)


def examination_choice(obj, primary, facts, blocked):
    if primary[:1] != ('SAY',) or primary[2] != 'ASK' or obj.get('urgent') is True or obj.get('prefer_exam') is not True:
        return primary, 'PRIMARY'
    option = obj.get('exam_option')
    if not isinstance(option, dict) or option.get('action', 'EXAM') != 'EXAM':
        return primary, 'INVALID_OPTION_IGNORED'
    basis, decision = option.get('basis_ids'), option.get('decision')
    if (not isinstance(basis, list) or not basis or any(not isinstance(i, str) or i not in {f['id'] for f in facts} for i in basis)
            or not isinstance(decision, str) or not 0 < len(decision.strip()) <= 240):
        return primary, 'INVALID_OPTION_IGNORED'
    try:
        return parse_action({'action': 'EXAM', 'content': option.get('content')}, blocked), 'EXAM_OPTION_SELECTED'
    except ValueError:
        return primary, 'INVALID_OPTION_IGNORED'
