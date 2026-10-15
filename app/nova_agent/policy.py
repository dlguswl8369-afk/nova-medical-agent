"""Research authorization is separate from publisher rights clearance."""
import json
from pathlib import Path

POLICY = json.loads((Path(__file__).resolve().parents[1] / 'assets/research_policy.json').read_text(encoding='utf-8'))


def research_decision(hit):
    source = hit.get('source_metadata', {})
    rule = POLICY['documents'].get(hit['document_id'])
    if source.get('explicit_publisher_llm_prohibition') or (rule and rule.get('publisher_llm_prohibition_confirmed')):
        return False, 'PUBLISHER_RESTRICTION'
    if not rule or rule['source_sha256'] != hit.get('source_sha256'):
        return False, 'UNREVIEWED_SOURCE_OR_HASH'
    if not rule['research_use_allowed']:
        return False, 'OUTSIDE_APPROVED_RESEARCH_SCOPE'
    if source.get('llm_processing_allowed') is False and source.get('llm_processing_restriction') not in rule['overridden_internal_flags']:
        return False, 'UNCLASSIFIED_LEGACY_RESTRICTION'
    if hit.get('review_status') == 'REJECTED' or hit.get('historical_ai_review_status') == 'REJECTED':
        return False, 'REJECTED_DERIVED_ITEM'
    return True, 'PROJECT_RESEARCH_AUTHORIZED_RIGHTS_NOT_CLEARED'
