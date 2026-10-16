"""Exact serialized final-message envelopes, including bounded repair messages."""
import json
from dataclasses import dataclass
from nova_sdk import NovaError
from .prompts import RECORD

# Fixed format-repair instruction. No generated text is appended.
RECORD_REPAIR = '\n기록 형식 또는 근거 ID 오류입니다. 실제 관찰 ID만 선택하고 예선 O.tests는 비우세요. source_refs에는 ID 목록만 씁니다. A는 인용 관찰의 범위 안에서 추론하며 부분 답변·모름을 다른 항목의 음성/정상으로 확대하지 마세요.'
SINGLE_INPUT_LIMIT = 100000
OUTPUT_CAP = 4096


def messages_for(system, user):
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]


def input_charge(system, user):
    # Same estimator as v3, not divided or calibrated to historical usage.
    return len(json.dumps(messages_for(system, user), ensure_ascii=False).encode('utf-8')) + 1024


@dataclass(frozen=True)
class RecordEnvelope:
    base_user: str
    attempts: int

    @property
    def charges(self):
        return tuple(input_charge(RECORD, self.base_user + RECORD_REPAIR * i) for i in range(self.attempts))

    def headroom(self, start=0):
        remaining = self.attempts - start
        return sum(self.charges[start:]), OUTPUT_CAP * remaining, remaining

    def validate(self, system, user, attempt):
        # The clinical context is frozen. Repairs can only add this literal suffix.
        if (not 0 <= attempt < self.attempts or system != RECORD
                or user not in (self.base_user + RECORD_REPAIR * i for i in range(attempt + 1))
                or input_charge(system, user) > self.charges[attempt]):
            raise NovaError('LOCAL_RECORD_ENVELOPE_MISMATCH')
        if self.charges[attempt] > SINGLE_INPUT_LIMIT:
            raise NovaError('LOCAL_SINGLE_PROMPT_BUDGET')

    def audit(self):
        charges = self.charges
        return {'base_input_estimate': charges[0], 'per_attempt_input_caps': list(charges),
            'repair_addition_per_step': [charges[i] - charges[i-1] for i in range(1, len(charges))],
            'maximum_repair_suffixes': self.attempts - 1, 'retry_clinical_context_growth_bytes': 0,
            'reserved_input': sum(charges), 'reserved_output': OUTPUT_CAP * self.attempts,
            'reserved_calls': self.attempts, 'estimator': 'UTF8_SERIALIZED_MESSAGES_PLUS_1024'}


def fit_record_envelope(user, attempts, available, *, mode):
    """Keep every observation; only remove complete lowest-ranked reference units.

    An unfundable observations-only packet fails closed. No text slicing and no
    dropped/shortened patient facts to manufacture a smaller reservation.
    """
    value = json.loads(user)
    envelope = RecordEnvelope(user, attempts)
    excluded = []
    original_count = len(value.get('reference_evidence', []))
    while True:
        headroom = envelope.headroom()
        feasible = (all(headroom[i] <= available[i] for i in range(3))
                    and max(envelope.charges) <= SINGLE_INPUT_LIMIT)
        if feasible:
            return envelope, {**envelope.audit(), 'mode': mode,
                'reference_units_before': original_count,
                'reference_units_after': len(value.get('reference_evidence', [])),
                'removed_reference_units': excluded, 'observations_removed': 0,
                'available_input': available[0], 'available_output': available[1], 'available_calls': available[2]}
        refs = value.get('reference_evidence', [])
        # A token-independent call/output deficit cannot be solved by removing text.
        if not refs or headroom[1] > available[1] or headroom[2] > available[2]:
            raise NovaError('LOCAL_FINAL_CONTEXT_BUDGET')
        removed = refs.pop()
        excluded.append({'unit_id': removed.get('unit_id'), 'reason': 'FINAL_RECORD_ENVELOPE_BUDGET'})
        envelope = RecordEnvelope(json.dumps(value, ensure_ascii=False), attempts)
