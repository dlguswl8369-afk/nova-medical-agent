"""Per-session planning and acknowledged communication, never a clinical answer key.

Model gap/coverage judgments are proposals, not observed patient facts. Only SDK
observations and exact quotations can enter the observation review ledger.
"""
import re
from .diagnostics import Rejection
from .progress import QuestionLedger, UNCERTAIN_REPLY, reaction_status, target_key

CORE_MESSAGES = ('uncertainty', 'plan', 'safety')
MESSAGE_KINDS = CORE_MESSAGES + ('empathy', 'understanding', 'purpose')
# Only explicit multiple request clauses are hard failures. Conjunctions and
# substrings inside words cannot establish the number of clinical goals.
MULTI_QUESTION = re.compile(r'[?？]\s*\S|(?:나요|습니까|까요)[,;]\s*\S|(?:나요|습니까|까요)\s+(?:그리고|또)\s+\S')
POSSIBLE_PARTIAL = re.compile(r'거나|이나\s|또는\s|[;,·]|[?？]\s*\S')
MULTI_EXAM = re.compile(r'(?:확인|촉진|청진|검사|관찰)(?:하고|하며|한 뒤)\s+\S|[;\n]\s*\S')


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
        self.questions = QuestionLedger()

    def pending_feedback(self):
        latest = {}
        for row in self.delivered:
            for kind in row['kinds']:
                latest[(target_key(row.get('target', '')), kind)] = row
        return list({row['observation_id']: row for row in latest.values()
                     if row.get('reaction') in ('needs_clarification', 'no_response', 'concern_expressed')}.values())

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
                elif f.get('intent') != 'EXPLAIN' and POSSIBLE_PARTIAL.search(f.get('question') or ''):
                    state = 'POSSIBLY_PARTIAL_REPLY'
            observations.append({'fact_id': f['id'], 'answer_scope': state,
                'explicit_quote_review_count': len(self.reviewed.get(f['id'], []))})
        return {'phase': self.phase, 'observations': observations,
            'model_proposed_gaps_not_patient_facts': [g | {'question_state': self.questions.latest().get(
                target_key(g['topic']), {}).get('status', 'not_asked')} for g in self.gaps],
            'acknowledged_explanations': self.delivered,
            'question_progress_not_clinical_facts': self.questions.context(),
            'explanations_needing_response_review': self.pending_feedback(),
            'communication_not_yet_acknowledged': missing,
            'boundary': 'Questions and gap labels are not facts. An exact quote does not prove every item in a question. '
                        'No inferred negative findings. Delivered tags are model classifications, not semantic certification.'}

    def validate(self, obj, step, facts):
        review = obj.get('review')
        if not isinstance(review, dict):
            raise Rejection('CONSULTATION_REVIEW_REQUIRED')
        by_id = {f['id']: f for f in facts}
        answer_reviews = self.questions.validate_updates(review.get('answer_reviews', []), facts)
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
        kinds, target = [], None
        if action != 'DONE':
            targets = obj.get('targets')
            if not isinstance(targets, list) or len(targets) != 1:
                raise Rejection('SINGLE_TARGET_REQUIRED')
            target = short(targets[0], 80)
            if not target_key(target):
                raise Rejection('SINGLE_TARGET_REQUIRED')
            short(obj.get('purpose'))
            if action == 'SAY' and intent == 'ASK' and MULTI_QUESTION.search(content):
                raise Rejection('COMPOUND_QUESTION')
            if action == 'SAY' and intent == 'ASK':
                self.questions.check_question(target, checked_gaps, answer_reviews)
            if action == 'EXAM' and MULTI_EXAM.search(content):
                raise Rejection('COMPOUND_EXAM')
            if action == 'SAY' and intent == 'EXPLAIN':
                kinds = obj.get('communication')
                if (not isinstance(kinds, list) or not kinds or len(kinds) > 3
                        or any(kind not in MESSAGE_KINDS for kind in kinds)):
                    raise Rejection('COMMUNICATION_KIND_REQUIRED')
                repeats = [r for r in self.delivered if target_key(r.get('target', '')) == target_key(target)
                           and set(r['kinds']) == set(kinds)]
                if len(repeats) >= 2:
                    raise Rejection('EXPLANATION_REPEAT_LIMIT')
                if repeats and repeats[-1].get('reaction') not in ('needs_clarification', 'no_response', 'concern_expressed'):
                    short(obj.get('new_explanation_reason'))
            if self.phase == 'CLOSE' and not kinds and not any(g['priority'] == 'high' for g in checked_gaps):
                raise Rejection('CLOSING_COMMUNICATION_REQUIRED')
        else:
            if review.get('ready_to_close') is not True:
                raise Rejection('PREMATURE_DONE')
            short(review.get('done_reason'))
            if checked_gaps or self.questions.unresolved_important(answer_reviews):
                short(review.get('defer_reason'))
            if self.pending_feedback():
                short(review.get('communication_defer_reason'))
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
                'answer_reviews': answer_reviews, 'target': target,
                'done_reason': review.get('done_reason') if action == 'DONE' else None,
                'defer_reason': review.get('defer_reason') if action == 'DONE' else None,
                'communication_defer_reason': review.get('communication_defer_reason') if action == 'DONE' else None,
                'not_applicable': review.get('not_applicable', {}) if action == 'DONE' else {}}

    def accept_review(self, review):
        self.gaps = review['gaps']
        self.questions.accept(review['answer_reviews'])
        for row in review['answered']:
            values = self.reviewed.setdefault(row['fact_id'], [])
            if row['quote'] not in values:
                values.append(row['quote'])
            del values[:-2]
        self.last_review = review

    def acknowledge(self, content, kinds, observation_id, reply=None, target=''):
        # Called only after a successful, structurally valid SDK action response.
        if kinds:
            self.delivered.append({'observation_id': observation_id, 'text': content, 'kinds': list(dict.fromkeys(kinds)),
                                   'reaction': reaction_status(reply), 'target': target})
