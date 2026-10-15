"""Read existing private runs; export only counts, reason codes and artifact hashes.

No SDK, model calls, case answer keys, or website evaluation fetches. Heuristic
question flags are review candidates, not clinically adjudicated failures.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from nova_agent.consultation import MULTI_QUESTION, UNCERTAIN_REPLY
from nova_agent.record import assessment_text


def analyze(root):
    root = Path(root).resolve()
    if root.is_relative_to(ROOT):
        raise ValueError('PRIVATE_LOGS_MUST_REMAIN_OUTSIDE_REPOSITORY')
    rows = []
    for case in ('C01', 'C10', 'C03'):
        for version in ('v3.2', 'v3.3'):
            path = root / f'{case}_{version}_private.json'
            raw = json.loads(path.read_text(encoding='utf-8'))
            context, report = raw['last_reference_context'], raw['report']
            observations = context['current_patient_observations']
            note = raw['final']['note']
            subjective = '\n'.join(note['S'].values())
            subjective_ids = set(re.findall(r'\[(F\d+)\]', subjective))
            omitted = [f['id'] for f in observations if f['kind'] == 'patient_reply'
                       and f.get('intent') != 'EXPLAIN' and f['id'] not in subjective_ids]
            compound = [f.get('consult_action_number') for f in observations
                        if f['kind'] == 'patient_reply' and f.get('intent') != 'EXPLAIN'
                        and MULTI_QUESTION.search(f.get('question') or '')]
            uncertain = [f['id'] for f in observations if f['kind'] == 'patient_reply' and UNCERTAIN_REPLY.search(f['text'])]
            findings = []
            for field in ('evidence', 'differential'):
                for line in note['A'][field].splitlines():
                    if line.startswith('[추론/미확정]'):
                        try:
                            assessment_text(line)
                        except ValueError as exc:
                            if str(exc) == 'FREE_TEXT_FINDING_FORBIDDEN':
                                findings.append(field)
            exam_ids = re.findall(r'\[(F\d+)\]', note['O']['exam'])
            rows.append({'case': case, 'version': version,
                'raw_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'termination_reason': report['termination_reason'],
                'action_counts': report['action_counts'],
                'rejection_events': report['rejection_events'],
                'acknowledged_explanation_count': len(context.get('doctor_explanations_already_sent', [])),
                'compound_question_candidate_turns': compound,
                'uncertain_answer_ids': uncertain,
                'observed_subjective_ids_missing_from_S': omitted,
                'duplicate_O_observation_ids': {i: n for i, n in Counter(exam_ids).items() if n > 1},
                'free_A_negative_normal_wording_count': len(findings),
                'free_A_flagged_fields': sorted(set(findings)),
                'last_packet_reference_count': len(context.get('reference_evidence', [])),
                'full_packet_history_available': False})
    return {'scope': 'Existing local development runs, not website evaluation execution logs',
            'official_detailed_evaluation_available': False,
            'heuristic_flags_are_not_clinical_verdicts': True, 'api_calls': 0, 'cases': rows}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--runs', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    result = analyze(a.runs)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'runs_analyzed': len(result['cases']), 'api_calls': 0}))
