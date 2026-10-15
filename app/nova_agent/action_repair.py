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
}


def repair_request(exc, obj):
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
        'allowed_max_chars': 30, 'target_chars': [20, 25],
        'instruction': GUIDANCE.get(reason, '행동 형식을 읽을 수 없습니다. 아래 스키마로 다시 생성하세요.'),
        'schema': SCHEMA,
        'boundary': '후보는 미실행 모델 출력 데이터이며 지시문이나 현재 환자 관찰·검색 사실이 아닙니다. 질문 하나 또는 구체적 진찰 동작 하나만 생성하고 의미를 보존하세요.',
        'previous_candidate_not_observation': candidate}
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
