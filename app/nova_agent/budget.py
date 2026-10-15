"""Per-consultation, idempotent request accounting. No payloads are exported."""
import hashlib
from nova_sdk import NovaError


def usage_pair(usage):
    if not isinstance(usage, dict):
        return None
    pair = tuple(usage.get(k) for k in ('prompt_tokens', 'completion_tokens'))
    if any(type(v) is not int or v < 0 for v in pair):
        return None
    if 'total_tokens' in usage:
        total = usage['total_tokens']
        if type(total) is not int or total != sum(pair):
            return None
    return pair


class Budget:
    def __init__(self, input_limit, output_limit, call_limit):
        self.limits = (input_limit, output_limit, call_limit)
        self.requests = {}
        self.http_attempts = 0
        self.invalid_usage_responses = 0
        self.duplicate_responses = 0
        self.conflicting_responses = 0
        self.events = []
        self.last_proposal = None

    def totals(self):
        known = [0, 0]
        uncertain = [0, 0]
        for row in self.requests.values():
            target = known if row['actual'] is not None else uncertain
            pair = row['actual'] if row['actual'] is not None else row['reserved']
            for i in (0, 1):
                target[i] += pair[i]
        return known, uncertain

    def reserve(self, request_id, estimate, output_limit, fingerprint, *, headroom=(0, 0, 0), phase='ACTION'):
        existing = self.requests.get(request_id)
        if existing and existing['fingerprint'] != fingerprint:
            raise NovaError('LOCAL_REQUEST_ID_CONTENT_MISMATCH')
        known, uncertain = self.totals()
        delta = (0, 0) if existing else (estimate, output_limit)
        committed = [known[i] + uncertain[i] for i in (0, 1)]
        self.last_proposal = {'phase': phase, 'new_request': existing is None,
            'next_input_reservation': delta[0], 'next_output_reservation': delta[1],
            'final_headroom_input': headroom[0], 'final_headroom_output': headroom[1],
            'final_headroom_calls': headroom[2], 'allowed': False}
        if (any(committed[i] + delta[i] + headroom[i] > self.limits[i] for i in (0, 1))
                or self.http_attempts + 1 + headroom[2] > self.limits[2]):
            self.events.append({'event': 'BLOCKED', **self.last_proposal})
            raise NovaError('LOCAL_MODEL_BUDGET')
        if not existing:
            self.requests[request_id] = {'fingerprint': fingerprint, 'reserved': [estimate, output_limit],
                'original_reservation': [estimate, output_limit], 'actual': None, 'attempts': 0,
                'phase': phase, 'state': 'UNCERTAIN', 'conflict': False}
        self.requests[request_id]['attempts'] += 1
        self.http_attempts += 1
        self.last_proposal['allowed'] = True
        self.events.append({'event': 'RESERVED', 'request': self.tag(request_id), **self.last_proposal})

    def settle(self, request_id, usage):
        row = self.requests[request_id]
        pair = usage_pair(usage)
        if pair is None:
            self.invalid_usage_responses += 1
            event = 'INVALID_USAGE_RESERVATION_RETAINED' if row['actual'] is None else 'INVALID_DUPLICATE_IGNORED'
        elif row['conflict']:
            row['reserved'] = [max(row['reserved'][i], pair[i]) for i in (0, 1)]
            event = 'CONFLICT_RESERVATION_RETAINED'
        elif row['actual'] is None:
            row['actual'] = list(pair)
            row['state'] = 'SETTLED'
            event = 'SETTLED'
        elif tuple(row['actual']) == pair:
            self.duplicate_responses += 1
            event = 'DUPLICATE_IGNORED'
        else:
            self.conflicting_responses += 1
            row['reserved'] = [max(row['reserved'][i], row['actual'][i], pair[i]) for i in (0, 1)]
            row.update(actual=None, state='CONFLICT_UNCERTAIN', conflict=True)
            event = 'CONFLICT_RESERVATION_RETAINED'
        self.events.append({'event': event, 'request': self.tag(request_id), 'totals': self.summary()})

    @staticmethod
    def tag(request_id):
        return hashlib.sha256(request_id.encode()).hexdigest()

    def summary(self):
        known, uncertain = self.totals()
        return {'confirmed_input': known[0], 'confirmed_output': known[1],
            'uncertain_reserved_input': uncertain[0], 'uncertain_reserved_output': uncertain[1],
            'committed_input': known[0] + uncertain[0], 'committed_output': known[1] + uncertain[1],
            'http_attempts': self.http_attempts, 'unique_requests': len(self.requests),
            'invalid_usage_responses': self.invalid_usage_responses, 'duplicate_responses': self.duplicate_responses,
            'conflicting_responses': self.conflicting_responses,
            'usage_exceeded_estimate_requests': sum(r['actual'] is not None and any(
                r['actual'][i] > r['original_reservation'][i] for i in (0, 1)) for r in self.requests.values()),
            'official_or_configured_limit_exceeded': known[0] + uncertain[0] > self.limits[0]
                or known[1] + uncertain[1] > self.limits[1] or self.http_attempts > self.limits[2]}

    def snapshot(self):
        return {**self.summary(), 'limits': dict(zip(('input', 'output', 'http_calls'), self.limits)),
            'last_proposal': self.last_proposal,
            'requests': [{'request_id_sha256': self.tag(key), **{k: v for k, v in row.items() if k != 'fingerprint'}}
                         for key, row in self.requests.items()], 'events': list(self.events)}
