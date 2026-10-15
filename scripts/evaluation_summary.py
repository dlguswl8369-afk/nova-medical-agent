"""Evidence-based review template; does not manufacture official/clinical scores."""
DOMAINS = {'정보수집': 25, '진단추론': 15, '검사·추적': 10, '안전': 15, '의사소통': 15, '효율': 20}


def summarize(events, final_record, agent_report=None):
    report=agent_report or {}
    successful=[e for e in events if e.get('response') and not e.get('error') and not e.get('refused')
                and not (isinstance(e['response'],dict) and (e['response'].get('refused') or e['response'].get('error'))) ]
    return {'official_score': False, 'diagnosis_accuracy_evaluated': False,
            'domains': {name: {'maximum': maximum, 'score': None, 'status': 'REQUIRES_LOG_AND_RECORD_REVIEW'}
                        for name,maximum in DOMAINS.items()},
            'evidence': {'successful_SAY': sum(e.get('action')=='SAY' for e in successful),
                         'successful_EXAM': sum(e.get('action')=='EXAM' for e in successful),
                         'record_present': bool(final_record),
                         'performed_actions_inferred_from_record': False},
            'retrieval': {'delivered_packets': report.get('retrieval_calls'),
                          'empty_packets': report.get('empty_retrievals'),
                          'max_packet_chars': report.get('max_reference_chars'),
                          'appropriateness': 'NOT_CLINICALLY_REVIEWED',
                          'reference_to_patient_contamination': 'REQUIRES_OBSERVATION_VS_RECORD_REVIEW'},
            'usage': {k: report.get(k) for k in ['doctor_http_attempts','doctor_successes',
                      'reported_prompt_tokens','reported_completion_tokens','duration_seconds']}}


def comparison_review_payload(left, right):
    """Only an evaluator outside the consultation may receive this payload."""
    return {'task': 'Self-reference comparison, NOT official scoring', 'domains': DOMAINS,
            'instructions': 'Use actual successful conversation/exam events AND the final record. '
            'Never infer performance from plans or the record alone. Do not invent missing evidence or scores. '
            'Check relevance, delivered source bodies, reference facts mistaken for patient facts, usage and duration.',
            'baseline': left, 'extended': right}
