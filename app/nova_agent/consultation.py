"""Per-session planning and acknowledged communication, never a clinical answer key.

Model gap/coverage judgments are proposals, not observed patient facts. Only SDK
observations and exact quotations can enter the observation review ledger.
"""
import re
from .diagnostics import Rejection

CORE_MESSAGES = ('uncertainty', 'plan', 'safety')
MESSAGE_KINDS = CORE_MESSAGES + ('empathy', 'understanding', 'purpose')
MULTI_QUESTION = re.compile(r'거나|그리고|또는|[;,·\n]|[?？].*\S|(?:이나|와|과)\s')
MULTI_EXAM = re.compile(r'그리고|(?:하고|하며)\s|및\s|[;\n]')
UNCERTAIN_REPLY = re.compile(r'모르|기억.*안|잘.*기억|한 번에 하나|확실.*않')


def short(value, maximum=180):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise Rejection('INVALID_CONSULTATION_REVIEW')
    return value.strip()


class DialogueState:
    def __init__(self):
        self.gaps = []
        self.reviewed = {}
        self.delivered = []
        self.phase = 'COLLECT'
        self.last_review = None

    def missing_messages(self):
        delivered = {kind for row in self.delivered for kind in row['kinds']}
        return [kind for kind in CORE_MESSAGES if kind not in delivered]

    def context(self, facts, turns_left, seconds_left, time_margin, budget_low=False):
        missing = self.missing_messages()
        # Conditional planning allowance, not a fixed number of mandatory actions.
        closing = bool(missing) and (turns_left <= len(missing) + 1
            or seconds_left <= time_margin + 60 * len(missing) or budget_low)
        self.phase = 'CLOSE' if closing else 'COLLECT'
        observations = []
        for f in facts:
            state = 'RECEIVED_NOT_INFERRED'
            if f['kind'] == 'patient_reply':
                if UNCERTAIN_REPLY.search(f['text']):
                    state = 'PATIENT_UNCERTAIN'
                elif f.get('intent') != 'EXPLAIN' and MULTI_QUESTION.search(f.get('question') or ''):
                    state = 'POSSIBLY_PARTIAL_REPLY'
            observations.append({'fact_id': f['id'], 'answer_scope': state,
                'explicit_quote_review_count': len(self.reviewed.get(f['id'], []))})
        return {'phase': self.phase, 'observations': observations,
            'model_proposed_gaps_not_patient_facts': self.gaps,
            'acknowledged_explanations': self.delivered,
            'communication_not_yet_acknowledged': missing,
            'boundary': 'Questions and gap labels are not facts. An exact quote does not prove every item in a question. '
                        'No inferred negative findings. Delivered tags are model classifications, not semantic certification.'}

    def validate(self, obj, step, facts):
        review = obj.get('review')
        if not isinstance(review, dict):
            raise Rejection('CONSULTATION_REVIEW_REQUIRED')
        by_id = {f['id']: f for f in facts}
        quotes = review.get('answered', [])
        gaps = review.get('gaps')
        if not isinstance(quotes, list) or len(quotes) > 4 or not isinstance(gaps, list) or len(gaps) > 6:
            raise Rejection('INVALID_CONSULTATION_REVIEW')
        checked_quotes, checked_gaps = [], []
        for row in quotes:
            if not isinstance(row, dict) or not isinstance(row.get('fact_id'), str) or row['fact_id'] not in by_id:
                raise Rejection('INVALID_REVIEW_OBSERVATION')
            quote = short(row.get('quote'), 240)
            if quote not in by_id[row['fact_id']]['text']:
                raise Rejection('REVIEW_QUOTE_NOT_OBSERVED')
            checked_quotes.append({'fact_id': row['fact_id'], 'quote': quote})
        for row in gaps:
            if not isinstance(row, dict):
                raise Rejection('INVALID_CONSULTATION_REVIEW')
            ids = row.get('basis')
            if (not isinstance(ids, list) or not 1 <= len(ids) <= 4
                    or any(not isinstance(i, str) or i not in by_id for i in ids)):
                raise Rejection('INVALID_REVIEW_OBSERVATION')
            if row.get('status') not in ('unknown', 'ambiguous') or row.get('priority') not in ('high', 'routine'):
                raise Rejection('INVALID_CONSULTATION_REVIEW')
            checked_gaps.append({'topic': short(row.get('topic'), 80), 'reason': short(row.get('reason')),
                'status': row['status'], 'priority': row['priority'], 'basis': ids})
        action, content, intent = step
        kinds = []
        if action != 'DONE':
            targets = obj.get('targets')
            if not isinstance(targets, list) or len(targets) != 1:
                raise Rejection('SINGLE_TARGET_REQUIRED')
            short(targets[0], 80)
            short(obj.get('purpose'))
            if action == 'SAY' and intent == 'ASK' and MULTI_QUESTION.search(content):
                raise Rejection('COMPOUND_QUESTION')
            if action == 'EXAM' and MULTI_EXAM.search(content):
                raise Rejection('COMPOUND_EXAM')
            if action == 'SAY' and intent == 'EXPLAIN':
                kinds = obj.get('communication')
                if (not isinstance(kinds, list) or not kinds or len(kinds) > 3
                        or any(kind not in MESSAGE_KINDS for kind in kinds)):
                    raise Rejection('COMMUNICATION_KIND_REQUIRED')
            if self.phase == 'CLOSE' and not kinds and not any(g['priority'] == 'high' for g in checked_gaps):
                raise Rejection('CLOSING_COMMUNICATION_REQUIRED')
        else:
            if review.get('ready_to_close') is not True:
                raise Rejection('PREMATURE_DONE')
            short(review.get('done_reason'))
            if checked_gaps:
                short(review.get('defer_reason'))
            exemptions = review.get('not_applicable', {})
            if not isinstance(exemptions, dict) or any(k not in CORE_MESSAGES for k in exemptions):
                raise Rejection('INVALID_CONSULTATION_REVIEW')
            for kind in self.missing_messages():
                # An exemption is an explicit case-dependent model judgment, never
                # a fabricated delivered SAY. Keep it visible in the final context.
                if kind not in exemptions:
                    raise Rejection('DONE_WITHOUT_COMMUNICATION')
                short(exemptions[kind])
        return {'gaps': checked_gaps, 'answered': checked_quotes, 'communication': kinds,
                'done_reason': review.get('done_reason') if action == 'DONE' else None,
                'defer_reason': review.get('defer_reason') if action == 'DONE' else None,
                'not_applicable': review.get('not_applicable', {}) if action == 'DONE' else {}}

    def accept_review(self, review):
        self.gaps = review['gaps']
        for row in review['answered']:
            values = self.reviewed.setdefault(row['fact_id'], [])
            if row['quote'] not in values:
                values.append(row['quote'])
            del values[:-2]
        self.last_review = review

    def acknowledge(self, content, kinds, observation_id):
        # Called only after a successful, structurally valid SDK action response.
        if kinds:
            self.delivered.append({'observation_id': observation_id, 'text': content, 'kinds': list(dict.fromkeys(kinds))})
