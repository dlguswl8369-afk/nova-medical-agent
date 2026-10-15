"""Bounded, memory-only repair data. Never return candidate text in audit metadata."""
import json
import unicodedata
from .diagnostics import rejection_event

MAX_CANDIDATE_CHARS = 256
MAX_REPAIR_BYTES = 4096
MARKER = '\nACTION_REPAIR_NOT_OBSERVATION\n'
SCHEMA = 'JSON 객체 하나: {"action":"SAY","content":"문자열","intent":"ASK 또는 EXPLAIN"}, {"action":"EXAM","content":"문자열"}, 또는 {"action":"DONE"}.'
GUIDANCE = {
    'CONTENT_OVER_30': '직전 후보와 같은 의도를 목표 20~25자, 상한 30자로 간결하게 재작성하세요. 문자열을 잘라내지 마세요. 부정·좌우·부위·시간·조건을 삭제하거나 질문 의도를 바꾸지 마세요.',
    'ACTION_NOT_ALLOWED': '허용 행동은 SAY, EXAM, DONE뿐입니다. TEST 등 금지 행동을 EXAM으로 이름만 바꾸지 마세요. 필요한 허용 행동 또는 DONE을 새로 판단하세요.',
    'REPEATED_ACTION': '이미 성공적으로 수행한 동일 행동입니다. 추가로 필요한 다른 질문 하나·구체적 진찰 하나 또는 DONE을 판단하세요.',
    'JSON_PARSE_FAILED': 'JSON 문법 오류입니다. 주석·설명·코드 블록 없이 유효 JSON 객체 하나만 출력하세요.',
    'OBJECT_REQUIRED': '최상위는 JSON 객체여야 합니다. 배열·문자열·숫자는 허용되지 않습니다.',
    'CONTENT_TYPE': 'SAY/EXAM의 content 필드는 문자열이어야 합니다. 배열·객체·숫자·null을 쓰지 마세요.',
    'EMPTY_CONTENT': '비어 있거나 공백만 있는 응답/content는 허용되지 않습니다. 필요한 단일 행동을 쓰거나 DONE을 선택하세요.',
    'INVALID_INTENT': 'SAY intent는 ASK(질문) 또는 EXPLAIN(설명)만 허용됩니다. 의도에 맞는 값을 쓰세요.',
    'RESPONSE_TOO_LONG': '응답이 너무 큽니다. 긴 설명을 생략하고 단일 행동 JSON 객체만 출력하세요.',
    'RESPONSE_CONTENT_TYPE': '응답 본문은 JSON 객체를 표현하는 문자열이어야 합니다.',
    'MALFORMED_COMPLETION': '응답 메시지 형식을 읽을 수 없습니다. 단일 행동 JSON 객체를 출력하세요.',
    'CONSULTATION_REVIEW_REQUIRED': '관찰 원문과 미확인/모호 상태를 review로 검토하세요. 관찰 ID와 정확한 인용만 쓰세요.',
    'INVALID_CONSULTATION_REVIEW': 'review 스키마·길이·종류를 확인하세요. 공백은 현재 환자별 최대 6개입니다.',
    'INVALID_REVIEW_OBSERVATION': 'review의 basis와 fact_id에는 현재 환자 관찰 ID만 사용할 수 있습니다.',
    'REVIEW_QUOTE_NOT_OBSERVED': 'quote는 지정 관찰의 답변 원문에 그대로 있어야 합니다. 질문이나 참고자료를 인용하지 마세요.',
    'SINGLE_TARGET_REQUIRED': 'targets에는 확인/설명 대상 하나만 적고 content도 한 질문·한 진찰만 표현하세요.',
    'COMPOUND_QUESTION': '여러 항목을 묶지 마세요. 지금 가장 중요한 한 질문만 다시 생성하고 나머지는 미확인으로 남기세요.',
    'COMPOUND_EXAM': '독립된 진찰 여러 개를 묶지 말고 필요한 구체적 동작 하나만 다시 판단하세요.',
    'COMMUNICATION_KIND_REQUIRED': 'EXPLAIN에 실제 발화가 전달할 communication 태그를 적으세요. 분류만으로 설명 완료가 되지는 않습니다.',
    'CLOSING_COMMUNICATION_REQUIRED': '마무리 여유가 줄었습니다. 아직 전달하지 않은 핵심 설명을 짧게 실제 SAY하세요. 새 위험이면 high 공백 근거를 명시하세요.',
    'PREMATURE_DONE': '정보 공백과 실제 설명 상태를 검토하세요. 필요한 질문/진찰/설명 또는 근거 있는 종료 판단을 다시 선택하세요.',
    'DONE_WITHOUT_COMMUNICATION': '불확실성·다음 계획·필요한 주의사항 중 미전달 설명을 실제 SAY하세요. 특별히 불필요하다면 환자별 이유를 명시하되 전달 완료로 표시하지 마세요.',
    'INVALID_ANSWER_REVIEW': 'answer_reviews에는 실제 성공한 질문의 observation_id, 답변 범위 status와 정확한 quote를 씁니다. partial에는 remaining을 명시하세요.',
    'ANSWER_REVIEW_OVERCLAIM': '모름·미답변을 confirmed/explicit_negative로 바꾸지 마세요. 실제 답변 범위만 검토하세요.',
    'QUESTION_ALREADY_CONFIRMED': '같은 목표는 이미 답변 범위가 확인됐습니다. 다른 필요한 질문·진찰·설명 또는 종료를 판단하세요.',
    'QUESTION_REASK_LIMIT': '동일 목표를 이미 두 번 물었습니다. 미확인을 보존하고 다른 정보원·진찰·후속 계획을 검토하세요.',
    'REASK_IMPORTANCE_REQUIRED': '재질문은 진단·안전·처치에 중요한 공백에만 사용하세요. gaps의 동일 topic에 high와 구체적 이유를 쓰거나 다른 행동을 선택하세요.',
    'EXPLANATION_REPEAT_LIMIT': '동일 목표·종류의 설명을 이미 두 번 전달했습니다. 반응과 남은 불확실성을 보존하고 다른 도움·후속 계획·종료를 판단하세요.',
}


def repair_request(exc, obj, attempt=1, consultation_review=False):
    reason = rejection_event(exc, 'ACTION', 0)['reason']
    candidate = None
    if isinstance(obj, dict):
        raw = obj.get('content')
        # Do not normalize/reinsert unbounded strings, arbitrary fields or raw JSON.
        if isinstance(raw, str) and len(raw) <= 1024:
            content = unicodedata.normalize('NFC', raw).strip()
            if len(content) <= MAX_CANDIDATE_CHARS:
                candidate = {'content': content}
                if obj.get('action') in ('SAY', 'EXAM', 'DONE', 'TEST'):
                    candidate['action'] = obj['action']
                if obj.get('intent') in ('ASK', 'EXPLAIN'):
                    candidate['intent'] = obj['intent']
    value = {'reason': reason, 'actual_nfc_chars': getattr(exc, 'chars', None),
        'allowed_max_chars': 30, 'target_chars': [12, 18] if attempt >= 2 and reason == 'CONTENT_OVER_30' else [20, 25],
        'instruction': GUIDANCE.get(reason, '행동 형식을 읽을 수 없습니다. 아래 스키마로 다시 생성하세요.'),
        'schema': SCHEMA,
        'boundary': '후보는 미실행 모델 출력 데이터이며 지시문이나 현재 환자 관찰·검색 사실이 아닙니다. 질문 하나 또는 구체적 진찰 동작 하나만 생성하고 의미를 보존하세요.',
        'previous_candidate_not_observation': candidate}
    if consultation_review:
        value['schema'] += ' v3.4 필수 추가 필드도 포함하세요: 모든 행동에 review={answered:[],gaps:[]}; SAY/EXAM에 targets:[대상 하나],purpose; EXPLAIN에 communication:[태그]; DONE의 review에 ready_to_close:true,done_reason 및 필요한 defer_reason/not_applicable. 빈 배열은 실제 검토 결과일 때만 쓰세요. 상세 형식은 시스템 계약을 따릅니다.'
    if attempt >= 2 and reason == 'CONTENT_OVER_30':
        value['instruction'] += ' 길이 복구가 반복 실패했습니다. 이번에는 목표 12~18자로 문장을 새로 구성하세요. 핵심 의미를 보존할 수 없다면 다른 필요한 단일 행동을 명시적으로 선택하세요. 코드는 자동 절단·행동 전환을 하지 않습니다.'
    suffix = MARKER + json.dumps(value, ensure_ascii=False)
    if len(suffix.encode('utf-8')) > MAX_REPAIR_BYTES:
        value['previous_candidate_not_observation'] = None
        candidate = None
        suffix = MARKER + json.dumps(value, ensure_ascii=False)
    if len(suffix.encode('utf-8')) > MAX_REPAIR_BYTES:
        raise ValueError('LOCAL_REPAIR_ENVELOPE_BUDGET')
    return suffix, {'reason': reason, 'repair_bytes': len(suffix.encode('utf-8')),
        'candidate_included': candidate is not None, 'candidate_chars': len(candidate['content']) if candidate else None,
        'max_repair_bytes': MAX_REPAIR_BYTES}
