"""Clinical proposals are separate from SDK-derived execution evidence."""
import copy
from .diagnostics import parse_action

MAX_GOALS = 8
MAX_SUPPLEMENTS = 6

GOALS = '''H7_GOALS_NOT_OBSERVATIONS
초기 실제 관찰 ID·질문/답변 원문·진찰을 읽고 이 환자에게 필요한 진료 목표만 생성하세요. 위험 확인/대응이 먼저입니다. 모든 유형이나 개수를 채우지 마세요. 충분하면 goals를 비워도 됩니다.
JSON {"goals":[{"id":"G1","kind":"ASK","importance":"important","reason":"판단에 필요한 이유","condition":"현재 환자에서 필요한 적용 조건","basis_ids":["F0"],"content":"실행 가능한 행동 하나","currently_needed":true}]}
kind는 ASK/EXAM/EXPLAIN, importance는 critical/important/optional입니다. 최대 8개는 저장 상한일 뿐 수행할 수가 아닙니다. ID는 짧은 영문/숫자/밑줄, reason과 condition은 각각 160자 이하, content는 NFC 30자 이하입니다. EXAM은 구체적 신체진찰 하나이며 TEST는 금지입니다.
병력·관련 양성/음성·위험 신호·신체진찰과 환자 질문 답변·불확실성·검사/치료/의뢰 이유·추적/악화 시 대처 중 현재 필요한 것을 선택하세요. 이미 충분히 확인하거나 설명한 것은 다시 만들지 마세요. 부분 답변·모름은 원문 범위만 인정하세요.
목표는 미시행 제안입니다. 수행·관찰·환자 이해를 주장하지 마세요. currently_needed는 현재 조건을 실제 원문과 대조한 판단이며 미리 모든 목표를 true로 만들지 마세요.'''


def call_settings(strategy, purpose, seconds_left):
    if strategy == 'H7' and purpose == 'GOALS':
        return 4096, 'medium'
    raise ValueError('AUXILIARY_PURPOSE_NOT_ENABLED')


def step_prompt(baseline, strategy):
    if strategy == 'BASELINE':
        return baseline
    if strategy != 'H7':
        raise ValueError('UNKNOWN_CLINICAL_STRATEGY')
    text = baseline.replace('검사 계획은 최종 P에만 적고', '검사는 미실시 계획으로 P에 적고 필요하면 SAY로 설명하며')
    return text + '''
H7 목표는 환자 사실이 아니라 미시행 행동 제안과 실제 실행 영수증입니다. 현재 긴급 확인/조치가 필요하면 기존 단일 행동과 urgent:true를 출력하세요. 목표보다 우선합니다.
closed_loop_not_patient_facts가 있으면 새 질문/답변·진찰 원문에 따라 목표 조건을 재판단하세요. 같은 ACTION JSON에 goal_review:{"revision":현재 revision,"needed":["현재도 필요한 목표 ID"],"withdraw":["불필요해진 목표 ID"]}를 선택적으로 붙이세요. 새 응답을 확인하지 않은 오래된 판단을 재사용하지 마세요.
부분 답변·모름·미답변은 수행 성공과 다릅니다. 필요한 나머지만 물어야 하면 goal_review.revise에 {"id":"G1","content":"새로운 구체적 재확인 하나","reason":"필요 이유","condition":"현재 적용 조건","basis_ids":["실제 관찰 ID"]}를 넣으세요. 의미 없는 표현 변경으로 같은 질문을 반복하지 마세요. 단순 완료 주장으로 수행 기록은 바뀌지 않습니다.
DONE을 선택해도 현재 다시 필요하다고 확인한 핵심 미수행 목표가 있으면 실행기가 하나를 수행할 수 있습니다. 충분하면 needed를 비우거나 불필요한 목표를 withdraw하고 DONE을 허용하세요. 성공한 ASK는 문진 내용의 확정이 아니고 EXPLAIN 성공은 이해 입증이 아닙니다. 목표 충족을 위해 위험 대응을 늦추거나 불필요한 행동을 만들지 마세요.'''


def key(step):
    return step[0], step[1], 'EXAM' if step[0] == 'EXAM' else step[2]


def goal_step(goal):
    return parse_action({'action': 'EXAM' if goal['kind'] == 'EXAM' else 'SAY',
                         'intent': goal['kind'], 'content': goal['content']}, set())


def valid_text(value, cap):
    return isinstance(value, str) and 0 < len(value.strip()) <= cap


def valid_basis(value, ids):
    return isinstance(value, list) and 0 < len(value) <= 8 and all(isinstance(i, str) and i in ids for i in value)


class GoalExecutor:
    def __init__(self):
        self.goals = {}
        self.revision = 0
        self.supplements = 0
        self.history = []

    def load(self, obj, facts, blocked):
        rows = obj.get('goals')
        if not isinstance(rows, list) or len(rows) > MAX_GOALS:
            raise ValueError('INVALID_GOAL_PLAN')
        ids, seen, ready = {f['id'] for f in facts}, set(), []
        for row in rows:
            if not isinstance(row, dict):
                continue
            gid = row.get('id')
            if (not valid_text(gid, 24) or not gid.isascii() or not all(c.isalnum() or c == '_' for c in gid)
                    or gid in self.goals or row.get('kind') not in ('ASK', 'EXAM', 'EXPLAIN')
                    or row.get('action', 'EXAM' if row.get('kind') == 'EXAM' else 'SAY') != ('EXAM' if row.get('kind') == 'EXAM' else 'SAY')
                    or row.get('importance') not in ('critical', 'important', 'optional')
                    or any(not valid_text(row.get(k), 160) for k in ('reason', 'condition'))
                    or not valid_basis(row.get('basis_ids'), ids)):
                continue
            try:
                step = goal_step(row)
            except ValueError:
                continue
            if (step[0], step[1]) in blocked or key(step) in seen:
                continue
            seen.add(key(step))
            goal = {k: copy.deepcopy(row[k]) for k in ('id', 'kind', 'importance', 'reason', 'condition', 'basis_ids')}
            goal.update(content=step[1], version=1, execution='pending', receipts=[], clinical_sufficiency='REVIEW')
            self.goals[gid] = goal
            if row.get('currently_needed') is True:
                ready.append(gid)
        self.revision += 1
        return ready

    def review(self, obj, facts, blocked):
        value = obj.get('goal_review')
        if not isinstance(value, dict) or type(value.get('revision')) is not int or value['revision'] != self.revision:
            return [], 'NO_FRESH_REVIEW'
        needed, withdraw, revise = value.get('needed', []), value.get('withdraw', []), value.get('revise', [])
        if (not isinstance(needed, list) or not isinstance(withdraw, list) or not isinstance(revise, list)
                or max(len(needed), len(withdraw), len(revise)) > MAX_GOALS
                or any(not isinstance(i, str) or i not in self.goals for i in needed + withdraw)):
            return [], 'INVALID_REVIEW_IGNORED'
        ids = {f['id'] for f in facts}
        for gid in withdraw:
            self.goals[gid]['execution'] = 'withdrawn'
            self.history.append({'event': 'WITHDRAWN', 'goal_id': gid, 'revision': self.revision})
        for change in revise:
            if not isinstance(change, dict) or not isinstance(change.get('id'), str):
                continue
            goal = self.goals.get(change['id'])
            if not goal or goal['id'] in withdraw:
                continue
            if (change.get('kind', goal['kind']) != goal['kind']
                    or change.get('action', 'EXAM' if goal['kind'] == 'EXAM' else 'SAY') != ('EXAM' if goal['kind'] == 'EXAM' else 'SAY')):
                continue
            if (any(not valid_text(change.get(k), 160) for k in ('reason', 'condition'))
                    or not valid_basis(change.get('basis_ids'), ids)):
                continue
            try:
                step = goal_step(dict(goal, content=change.get('content')))
            except ValueError:
                continue
            if step[1] == goal['content'] or (step[0], step[1]) in blocked:
                continue
            goal.update(content=step[1], reason=change['reason'], condition=change['condition'],
                        basis_ids=copy.deepcopy(change['basis_ids']), execution='pending', version=goal['version'] + 1)
            self.history.append({'event': 'REVISED', 'goal_id': goal['id'], 'version': goal['version']})
        self.revision += 1
        return list(dict.fromkeys(needed)), 'CURRENT_REVIEW'

    def choose(self, needed, blocked):
        if self.supplements >= MAX_SUPPLEMENTS:
            return None
        for gid in needed:
            goal = self.goals.get(gid)
            if not goal or goal['execution'] != 'pending' or goal['importance'] not in ('critical', 'important'):
                continue
            step = goal_step(goal)
            if (step[0], step[1]) not in blocked:
                self.supplements += 1
                self.history.append({'event': 'DONE_DEFERRED', 'goal_id': gid, 'version': goal['version'],
                                     'supplement': self.supplements})
                return step
        return None

    def record(self, step, observation_id=None, failure=None):
        # Called exclusively after SDK acknowledgement/observation insertion,
        # or on the SDK failure path. Model completion fields are never read.
        for goal in self.goals.values():
            if key(goal_step(goal)) != key(step):
                continue
            receipt = {'version': goal['version'], 'observation_id': observation_id,
                       'status': 'SDK_SUCCEEDED' if observation_id is not None else 'SDK_FAILED'}
            if failure:
                receipt['failure'] = failure
            goal['receipts'].append(receipt)
            goal['execution'] = 'performed' if observation_id is not None else 'failed'
            self.history.append({'event': receipt['status'], 'goal_id': goal['id'], **receipt})
        self.revision += 1  # Every new reply or failure invalidates older reviews.

    def context(self):
        return {'revision': self.revision, 'supplements_used': self.supplements,
                'warning': 'Execution receipts only. ASK information and patient understanding are not confirmed.',
                'goals': copy.deepcopy(list(self.goals.values()))}

    def audit(self):
        return {'supplements': self.supplements, 'events': copy.deepcopy(self.history),
                'goals': [{k: copy.deepcopy(g[k]) for k in ('id', 'kind', 'version', 'execution', 'receipts', 'clinical_sufficiency')}
                          for g in self.goals.values()]}
