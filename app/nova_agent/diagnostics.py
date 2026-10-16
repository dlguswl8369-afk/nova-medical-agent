"""Only fixed reason codes and lengths; never model or patient content."""
import json
import unicodedata

RECORD_CODES = frozenset(('INVALID_RECORD_STRING', 'INVALID_RECORD_OBJECT', 'ONE_DIAGNOSIS_REQUIRED',
    'UNKNOWN_OBSERVATION_ID', 'OBSERVATION_SOURCE_MISMATCH', 'DIAGNOSIS_BASIS_REQUIRED',
    'INVALID_SOURCE_REFS', 'INVALID_SOURCE_FIELDS', 'PRELIMINARY_TEST_RESULTS_FORBIDDEN',
    'INVALID_ASSESSMENT', 'ASSESSMENT_BASIS_REQUIRED', 'INVALID_PLAN_FIELDS', 'RECORD_BYTE_BUDGET'))


class Rejection(ValueError):
    def __init__(self, code, chars=None):
        super().__init__(code)
        self.code, self.chars = code, chars


def parse_object(text):
    if not isinstance(text, str):
        raise Rejection('RESPONSE_CONTENT_TYPE')
    if len(text) > 32000:
        raise Rejection('RESPONSE_TOO_LONG', len(text))
    if not text.strip():
        raise Rejection('EMPTY_CONTENT', len(text))
    text = text.strip()
    if text.startswith('```json') and text.endswith('```'):
        text = text[7:-3].strip()
    try:
        value = json.loads(text)
    except ValueError:
        raise Rejection('JSON_PARSE_FAILED', len(text)) from None
    if not isinstance(value, dict):
        raise Rejection('OBJECT_REQUIRED', len(text))
    return value


def parse_action(obj, performed):
    action = obj.get('action')
    if action == 'DONE':
        return 'DONE', '', ''
    if action not in ('SAY', 'EXAM'):
        raise Rejection('ACTION_NOT_ALLOWED')
    raw = obj.get('content')
    if not isinstance(raw, str):
        raise Rejection('CONTENT_TYPE')
    content = unicodedata.normalize('NFC', raw).strip()
    if not content:
        raise Rejection('EMPTY_CONTENT', 0)
    if len(content) > 30:
        raise Rejection('CONTENT_OVER_30', len(content))
    if (action, content) in performed:
        raise Rejection('REPEATED_ACTION', len(content))
    intent = obj.get('intent', 'ASK')
    if action == 'SAY' and intent not in ('ASK', 'EXPLAIN'):
        raise Rejection('INVALID_INTENT', len(content))
    return action, content, intent


def rejection_event(exc, phase, call_number):
    code = exc.code if isinstance(exc, Rejection) else str(exc)
    if not isinstance(exc, Rejection) and code not in RECORD_CODES | {'MALFORMED_COMPLETION'}:
        code = 'UNCLASSIFIED_FORMAT_ERROR'
    return {'phase': phase, 'reason': code, 'content_chars': getattr(exc, 'chars', None),
            'doctor_http_attempt': call_number}
