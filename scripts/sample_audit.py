"""In-memory payload verification; export counts/IDs only, never clinical text."""
import hashlib
import json
import re


def integer(value):
    return value if type(value) is int and value >= 0 else None


class SampleAudit:
    def __init__(self):
        self.calls = []
        self.actions = []
        self.initial = {}
        self.facts = {}

    def chat_request(self, body):
        row = {'model': body.get('model') if body.get('model') == 'openai/gpt-6-luna' else 'OTHER_OR_MISSING',
               'reasoning_effort': body.get('reasoning_effort') if body.get('reasoning_effort') in ('low', 'medium', 'high') else 'OTHER_OR_MISSING',
               'max_tokens': integer(body.get('max_tokens')), 'transport_succeeded': False,
               'request_id_sha256': hashlib.sha256(str(body.get('request_id', '')).encode()).hexdigest()}
        contexts = []
        for msg in body.get('messages', []):
            if msg.get('role') != 'user' or not isinstance(msg.get('content'), str):
                continue
            try:
                value, _ = json.JSONDecoder().raw_decode(msg['content'].lstrip())
                if isinstance(value, dict) and 'current_patient_observations' in value:
                    contexts.append(value)
            except ValueError:
                pass
        refs = [r for ctx in contexts for r in ctx.get('reference_evidence', []) if isinstance(r, dict)]
        facts = [f for ctx in contexts for f in ctx.get('current_patient_observations', []) if isinstance(f, dict)]
        self.facts.update({f['id']: f for f in facts if isinstance(f.get('id'), str)})
        def verified(f):
            if f.get('kind') == 'opening':
                value = self.initial.get('opening')
            elif f.get('kind') == 'vitals':
                value = self.initial.get('vital_signs')
            else:
                action = 'SAY' if f.get('kind') == 'patient_reply' else 'EXAM' if f.get('kind') == 'exam' else None
                return any(a == action and q == f.get('question') and answer == f.get('text') for a, q, answer in self.actions)
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
            return f.get('text') == text
        row.update(nonempty_reference_count=sum(bool(r.get('text')) for r in refs),
            reference_body_chars=sum(len(r.get('text', '')) for r in refs),
            reference_fact_boundary=all(r.get('not_current_patient_facts') is True for r in refs),
            fact_ids=[f['id'] for f in facts if re.fullmatch(r'F\d+', str(f.get('id', '')))],
            paired_interview_count=sum(f.get('kind') == 'patient_reply' and bool(f.get('question')) for f in facts),
            paired_exam_count=sum(f.get('kind') == 'exam' and bool(f.get('question')) for f in facts),
            observations_match_sdk_responses=all(verified(f) for f in facts),
            context_present=bool(contexts))
        self.calls.append(row)
        return row

    def chat_response(self, row, response):
        row['transport_succeeded'] = True
        returned=response.get('model') if isinstance(response,dict) else None
        row['returned_model_id']=returned if returned=='openai/gpt-6-luna' else ('NOT_PROVIDED' if returned is None else 'OTHER_MODEL_ID')
        usage = response.get('usage') if isinstance(response, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        row['usage'] = {k: integer(usage.get(k)) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
        row['usage_missing_fields'] = [k for k, v in row['usage'].items() if v is None]
        choices = response.get('choices', []) if isinstance(response, dict) else []
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        message = choice.get('message', {})
        content = message.get('content') if isinstance(message, dict) else None
        finish = choice.get('finish_reason')
        row.update(content_chars=len(content) if isinstance(content, str) else None,
                   empty_content=not isinstance(content, str) or not content.strip(),
                   finish_reason=finish if finish in ('stop', 'length', 'content_filter', 'tool_calls', 'function_call', None) else 'OTHER',
                   finish_reason_missing=finish is None,
                   reported_truncation=finish == 'length',
                   output_at_requested_limit=(row['usage']['completion_tokens'] >= row['max_tokens'])
                       if row['usage']['completion_tokens'] is not None and row['max_tokens'] else None)

    def action_response(self, body, response):
        action = body.get('action')
        field = {'SAY': 'content', 'EXAM': 'result'}.get(action)
        if field and isinstance(response, dict) and isinstance(response.get(field), str):
            self.actions.append((action, body.get('content'), response[field]))

    def record_check(self, note):
        from nova_agent.record import format_fact
        ids = set()
        unknown = set()
        exact = True
        for section in ('S', 'O'):
            for value in note[section].values():
                lines = value.splitlines()
                # Every S/O block must match a complete renderer-produced observation.
                matches = list(re.finditer(r'(?m)^\[(F\d+)\]', value))
                if value.strip() and not matches:
                    exact = False
                for i, match in enumerate(matches):
                    fid = match.group(1); ids.add(fid)
                    text = value[match.start():matches[i+1].start() if i+1 < len(matches) else len(value)].rstrip()
                    if fid not in self.facts:
                        unknown.add(fid); exact = False
                    elif text != format_fact(self.facts[fid]).rstrip():
                        exact = False
        return {'observation_ids': sorted(ids), 'unknown_observation_ids': sorted(unknown),
                'so_matches_observed_fact_rendering': exact, 'objective_tests_empty': note['O']['tests'] == ''}

    def report(self):
        return {'doctor_response_checks': self.calls, 'performed_say_count': sum(a == 'SAY' for a, _, _ in self.actions),
                'performed_exam_count': sum(a == 'EXAM' for a, _, _ in self.actions),
                'patient_text_or_model_content_exported': False}
