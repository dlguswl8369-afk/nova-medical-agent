"""Bounded adaptive planning and fresh, one-action coverage selection."""
import unicodedata

from .diagnostics import parse_action

FEATURES = {'BASELINE': (), 'H5': ('workflow',), 'H6': ('coverage', 'audit')}

PLAN = '''ADAPTIVE_PLAN_NOT_PATIENT_FACTS
현재 관찰 ID와 질문·답변·진찰 원문만 환자 사실입니다. 참고자료와 미실시 계획은 구별하세요.
이 환자의 주호소에서 필요한 병력·관련 양성/음성·위험 신호·신체진찰·설명·검사/의뢰/추적/악화 시 대처를 간결한 잠정 계획으로 정리하세요. 이미 확보한 답변, 부분 답변, 모름을 구별하고 중요한 미확인 사항이 실제 진단·처치를 어떻게 바꾸는지 고려하세요.
고정 목록이나 확진을 만들지 마세요. 새 답변과 다르면 가설을 버리세요. 위험 확인/대응이 필요하면 다른 확인보다 우선하세요.
JSON {"plan":"관찰 ID와 미확인 내용을 구별한 환자별 계획, 1600자 이내", "next_action":{"action":"SAY","intent":"ASK","content":"질문 하나"}}
next_action은 선택 사항입니다. SAY(ASK/EXPLAIN), EXAM, DONE 중 가장 필요한 행동 하나를 제안하세요. SAY/EXAM은 NFC 30자 이하이며 EXAM은 구체적 신체진찰 동작 하나입니다. TEST와 미시행 검사결과 생성은 금지합니다.
계획은 수행 기록이 아니며 설명 제안은 전송 완료나 환자 이해의 증거가 아닙니다. 이미 필요한 확인이 충분하면 그 이유를 계획에 짧게 적고 불필요한 행동을 만들지 마세요.'''

REFRESH = '''ADAPTIVE_REFRESH_NOT_PATIENT_FACTS
Doctor가 종료를 고려하는 시점입니다. 잠정 계획 이후 실제 답변·진찰 결과를 다시 읽고, 틀린 가설과 이미 확인된 항목을 정리하세요. 직접 질문·이해 곤란·필요한 실제 설명도 확인하세요.
중요한 미확인 병력·진찰·검사/의뢰/추적/안전 안내가 남았다면 지금 필요한 행동 하나를 next_action으로 제안하고 plan을 갱신하세요. 충분하면 DONE을 허용하세요. 목록을 채우거나 반복을 강제하지 마세요.
''' + PLAN

AUDIT = '''COVERAGE_AUDIT_NOT_PATIENT_FACTS
첫 종료 선택을 현재 관찰 ID·질문/답변 원문·시행한 진찰·실제 SAY와 대조하세요.
이 환자의 주호소에서 중요한 병력·관련 증상·위험 신호·진찰, 직접 질문 답변, 검사/처치/의뢰/추적의 이유와 구체적 악화 시 대처에 실제 누락이 있는지 판단하세요. 부분 답변을 다른 항목의 음성으로 확대하지 마세요. P 계획만으로 설명 완료라 보지 마세요.
중요한 미확인 사항이 있으면 ASK/EXAM/EXPLAIN 중 가장 필요한 한 행동을 제안하세요. 충분하거나 추가 확인의 가치가 낮으면 {"action":"DONE"}을 허용하세요. 무조건 추가하지 마세요.
JSON {"action":"SAY","intent":"ASK 또는 EXPLAIN","content":"한 뜻, NFC 30자 이하"} 또는 {"action":"EXAM","content":"구체적인 신체진찰 하나"}.
긴급 확인/대응을 지연하지 마세요. TEST와 미시행 결과 생성은 금지합니다. 단순 동의·전송 성공을 환자 이해로 판단하지 마세요.'''


def features(strategy):
    if strategy not in FEATURES:
        raise ValueError('UNKNOWN_CLINICAL_STRATEGY')
    return FEATURES[strategy]


def call_settings(strategy, purpose, seconds_left):
    enabled = features(strategy)
    if (purpose in ('PLAN', 'REFRESH') and 'workflow' in enabled) or (purpose == 'AUDIT' and 'audit' in enabled):
        return 3072, 'medium'
    raise ValueError('AUXILIARY_PURPOSE_NOT_ENABLED')


def step_prompt(baseline, strategy):
    enabled = features(strategy)
    if not enabled:
        return baseline
    text = baseline.replace('검사 계획은 최종 P에만 적고', '검사는 미실시 계획으로 P에 적고 필요하면 SAY로 설명하며')
    if 'workflow' in enabled:
        text += '\n긴급한 초기 확인을 먼저 수행하세요. 지금 긴급한 확인/조치를 해야 한다면 urgent:true로 표시하세요. planning_ready는 필요 없습니다. clinical_plan_not_patient_facts는 미실시 잠정 계획입니다. 새 원문 답변과 대조하여 중요한 미확인 항목을 다음 행동에 반영하고, 가설이 달라지거나 답변이 확보되면 같은 ACTION에 plan_update 문자열(1600자 이내)로 수정하세요. 계획보다 현재 환자의 반응이 우선입니다.'
    if 'coverage' in enabled:
        text += '\n진단 이름이나 빠른 종료보다 현재 주호소에 필요한 문진·진찰·실제 설명의 이행을 판단하세요. 다음 행동을 비교할 때 JSON next_actions 배열에 중요도 순으로 최대 3개 대안을 담을 수 있습니다. 각 대안은 기존 행동 JSON과 basis_ids(실제 관찰 ID), decision(판단을 바꾸는 이유, 160자 이내)을 포함합니다. 가장 먼저 유효한 행동 하나만 실행하며 나머지는 폐기합니다. 다음 응답 후 다시 판단하므로 고정 순서나 목록을 만들지 마세요. 모든 종류의 행동을 채울 필요는 없습니다. 충분하면 기존 DONE을 출력하세요. 급한 경우 대안 대신 단일 행동에 urgent:true를 붙이세요. 유효한 단일 행동도 항상 허용됩니다.'
    return text + '\n계획·실패 이력·미실시 대안은 환자 사실이나 완료 기록이 아닙니다. 질문한 사실과 답변 확보를 구별하고, 필요 설명은 실제 SAY(EXPLAIN)로 전달하세요. P 작성·전송 성공·환자 이해는 각각 다릅니다.'


def plan_text(value):
    if not isinstance(value, str):
        return None
    value = unicodedata.normalize('NFC', value).strip()
    return value if 0 < len(value) <= 1600 else None


def audit_action(value, blocked):
    if value.get('action') in ('ASK', 'EXPLAIN'):
        value = dict(value, action='SAY', intent=value['action'])
    return parse_action(value, blocked)


def coverage_action(obj, facts, blocked):
    # A primary TEST/invalid action is never rescued by converting it to EXAM.
    primary = parse_action(obj, blocked) if 'action' in obj else None
    if obj.get('urgent') is True and primary is not None:
        return primary, 'URGENT_PRIMARY'
    options = obj.get('next_actions')
    ids = {f['id'] for f in facts}
    if isinstance(options, list) and 0 < len(options) <= 3:
        for option in options:
            if not isinstance(option, dict):
                continue
            basis, decision = option.get('basis_ids'), option.get('decision')
            if (not isinstance(basis, list) or not basis or any(not isinstance(i, str) or i not in ids for i in basis)
                    or not isinstance(decision, str) or not 0 < len(decision.strip()) <= 160):
                continue
            try:
                proposed = parse_action(option, blocked)
                if proposed[0] != 'DONE':
                    return proposed, 'FRESH_COVERAGE_ACTION'
            except ValueError:
                continue
    if primary is not None:
        return primary, 'PRIMARY'
    raise ValueError('INVALID_COVERAGE_ACTION')
