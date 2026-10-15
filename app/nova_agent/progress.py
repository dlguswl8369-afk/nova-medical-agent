"""Session-only question goals; a received reply is not a confirmed finding."""
import re
import unicodedata
from .diagnostics import Rejection

UNCERTAIN_REPLY = re.compile(r'모르|모릅|몰라|기억.*(?:안|않)|확실.*않')
UNANSWERED_REPLY = re.compile(r'답(?:변)?하고 싶지|말하고 싶지|못 들|다시 질문|질문.*이해.*못')
CLARIFICATION = re.compile(r'이해.*(?:못|안)|무슨 (?:말|뜻)|다시 설명|잘 모르|못 들|어렵(?:네요|어요)')
NEGATIVE_REPLY = re.compile(r'아니요|아니에요|없|않|안\s|부인|\b(?:no|not|deny|denies|without)\b', re.I)
CONFIRMED = {'confirmed', 'explicit_negative'}
STATUSES = CONFIRMED | {'unknown', 'ambiguous', 'unanswered', 'partial'}


def target_key(text):
    return re.sub(r'\W+', '', unicodedata.normalize('NFC', text).casefold())


def reply_status(text):
    if not text.strip() or UNANSWERED_REPLY.search(text):
        return 'unanswered'
    if UNCERTAIN_REPLY.search(text):
        return 'unknown'
    return 'received_unreviewed'


def reaction_status(text):
    if text is None:
        return 'not_assessed'
    if not text.strip():
        return 'no_response'
    if CLARIFICATION.search(text):
        return 'needs_clarification'
    if re.search(r'걱정|무서|불안', text):
        return 'concern_expressed'
    return 'response_received_understanding_unverified'


class QuestionLedger:
    def __init__(self):
        self.rows = []

    def validate_updates(self, updates, facts):
        if not isinstance(updates, list) or len(updates) > 4:
            raise Rejection('INVALID_ANSWER_REVIEW')
        by_id = {r['observation_id']: r for r in self.rows}
        observations = {f['id']: f for f in facts}
        result, seen = [], set()
        for item in updates:
            if not isinstance(item, dict) or not isinstance(item.get('observation_id'), str):
                raise Rejection('INVALID_ANSWER_REVIEW')
            fid, status, quote = item['observation_id'], item.get('status'), item.get('quote', '')
            if fid not in by_id or fid not in observations or fid in seen or not isinstance(status, str) or status not in STATUSES:
                raise Rejection('INVALID_ANSWER_REVIEW')
            seen.add(fid)
            text = observations[fid]['text']
            if not isinstance(quote, str) or len(quote) > 240 or (quote and quote not in text):
                raise Rejection('REVIEW_QUOTE_NOT_OBSERVED')
            if status in CONFIRMED and (not quote.strip() or reply_status(text) in ('unknown', 'unanswered')):
                raise Rejection('ANSWER_REVIEW_OVERCLAIM')
            if status == 'explicit_negative' and not NEGATIVE_REPLY.search(quote):
                raise Rejection('ANSWER_REVIEW_OVERCLAIM')
            remaining = item.get('remaining', '')
            if not isinstance(remaining, str) or len(remaining) > 120 or (status == 'partial' and not remaining.strip()):
                raise Rejection('INVALID_ANSWER_REVIEW')
            result.append({'observation_id': fid, 'status': status, 'quote': quote, 'remaining': remaining})
        return result

    def latest(self, updates=()):
        changes = {r['observation_id']: r for r in updates}
        rows = {}
        for row in self.rows:
            value = row | changes.get(row['observation_id'], {})
            rows[target_key(row['target'])] = value
        return rows

    def check_question(self, target, gaps, updates):
        key = target_key(target)
        prior = self.latest(updates).get(key)
        if prior is None:
            return
        if prior['status'] in CONFIRMED:
            raise Rejection('QUESTION_ALREADY_CONFIRMED')
        if sum(target_key(r['target']) == key for r in self.rows) >= 2:
            raise Rejection('QUESTION_REASK_LIMIT')
        if not any(target_key(g['topic']) == key and g['priority'] == 'high' for g in gaps):
            raise Rejection('REASK_IMPORTANCE_REQUIRED')

    def unresolved_important(self, updates=()):
        return [r for r in self.latest(updates).values() if r['priority'] == 'high' and r['status'] not in CONFIRMED]

    def accept(self, updates):
        changes = {r['observation_id']: r for r in updates}
        for row in self.rows:
            row.update(changes.get(row['observation_id'], {}))

    def observe(self, observation, target, gaps):
        priority = 'high' if any(target_key(g['topic']) == target_key(target) and g['priority'] == 'high' for g in gaps) else 'routine'
        self.rows.append({'observation_id': observation['id'], 'target': target, 'priority': priority,
            'status': reply_status(observation['text']), 'quote': '', 'remaining': ''})

    def context(self):
        latest = list(self.latest().values())
        important = self.unresolved_important()
        selected = {r['observation_id'] for r in important[:12] + latest[-12:]}
        return {'goals': [{k: v for k, v in r.items() if k != 'quote'} | {'has_exact_reply_quote': bool(r['quote'])}
                         | {'asked_count': sum(target_key(old['target']) == target_key(r['target']) for old in self.rows)}
                         for r in latest if r['observation_id'] in selected],
                'omitted_goal_count': len(latest) - len(selected),
                'important_unresolved_count': len(important),
                'boundary': 'Model answer reviews are scope judgments, not independent clinical verification. '
                            'Unreviewed/unknown/partial/unanswered are never negative findings. Keep goal labels stable.'}
