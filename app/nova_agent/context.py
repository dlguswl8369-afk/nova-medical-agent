"""Whole observations and source units; no reference fact becomes patient data."""
import json
import re
from pathlib import Path
from nova_retrieval.tokenize import tokenize
from .policy import research_decision

UNITS = json.loads((Path(__file__).resolve().parents[1] / 'assets/evidence_units.json').read_text(encoding='utf-8'))


def observation_text(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def fact(fid, kind, text, question=None):
    if not isinstance(text, str) or len(text) > 16000:
        raise ValueError('INVALID_OBSERVATION')
    return {'id': fid, 'kind': kind, 'text': text, 'question': question}


def observation_unit(f):
    if f['kind'] == 'patient_reply':
        if not f.get('question') or f.get('intent') == 'EXPLAIN':
            return None
        return f"[{f['id']}] 문진 질문(확인된 사실 아님): {f['question']} / 환자 답변: {f['text']}"
    if f['kind'] == 'exam':
        if not f.get('question'):
            return None
        return f"[{f['id']}] 실제 시행한 진찰: {f['question']} / 결과: {f['text']}"
    if f['kind'] in ('opening', 'vitals'):
        return f"[{f['id']}] {'시작 정보' if f['kind'] == 'opening' else '제공 활력징후'}: {f['text']}"
    return None


def query_from_facts(facts, limit=1800, audit=None):
    """Keep whole pairs with separate early-history and recent-response quotas.

    Salience changes selection only. Lexical search does not infer polarity.
    The full observation ledger is not changed by search-budget omissions.
    """
    if limit < 1:
        raise ValueError('INVALID_QUERY_BUDGET')
    units = {i: observation_unit(f) for i, f in enumerate(facts)}
    selected, total = set(), 0
    def take(i, quota=None):
        nonlocal total
        text = units[i]
        cost = len(text) + bool(selected) if text else limit + 1
        if i in selected or total + cost > limit or (quota is not None and cost > quota):
            return False
        selected.add(i); total += cost
        return True
    initial = [i for i, f in enumerate(facts) if f['kind'] in ('opening', 'vitals')]
    for i in initial:
        take(i, limit // 2 - total)
    interactions = [i for i, f in enumerate(facts) if f['kind'] in ('patient_reply', 'exam') and units[i]]
    salient = [i for i in interactions if re.search(r'약|복용|항생제|알레르기|언제|시작|과거|수술|임신|기저|medicat|allerg|onset', facts[i].get('question', ''), re.I)]
    early_budget = (limit - total) // 2
    early_start = total
    for i in list(dict.fromkeys(salient + interactions[:4])):
        take(i, early_budget - (total - early_start))
    for i in reversed(interactions):
        take(i)
    for i in initial + interactions:
        take(i)
    output = '\n'.join(units[i] for i in sorted(selected))
    if audit is not None:
        audit.update(included_ids=[facts[i]['id'] for i in sorted(selected)],
            excluded=[{'id': f['id'], 'reason': 'WHOLE_UNIT_BUDGET' if units[i] else 'NOT_PAIRED_EXECUTED_OBSERVATION'} for i, f in enumerate(facts) if i not in selected],
            chars=len(output), limit=limit, polarity_rewritten=False)
    return output


def evidence_candidates(index, hit, query):
    """Use complete heading sections, page units or existing case table export.

    HTML h2 sections retain nested lists and exceptions. PDF pages remain whole.
    No free-form sentence/character splitting is used to reduce a source unit.
    """
    units = UNITS.get(hit['parent_id'], [])
    span = hit.get('source_span')
    terms = set(tokenize(query, 'ko_bigram'))
    candidates = []
    for unit in units:
        if span and not (unit['end'] > span['start'] and unit['start'] < span['end']):
            continue
        text = unit.get('text')
        if text is None:
            text = index.get_parent(hit['parent_id'])['text'][unit['start']:unit['end']]
        if not text.strip():
            continue
        coverage = len(terms & set(tokenize(text, 'ko_bigram')))
        candidates.append((coverage, unit, text))
    # A matched window can span an instruction and an exception in adjacent h2
    # sections. Prefer their intact contiguous envelope before smaller sections.
    if span and len(candidates) > 1 and all(u['field']=='text' for _,u,_ in candidates):
        start=min(u['start'] for _,u,_ in candidates);end=max(u['end'] for _,u,_ in candidates)
        text=index.get_parent(hit['parent_id'])['text'][start:end]
        unit={'unit_id':f"{hit['parent_id']}:envelope:{start}:{end}", 'start':start,'end':end,'field':'text',
            'scope':'COMPLETE_MATCHED_SECTION_ENVELOPE','heading':' / '.join(u['heading'] for _,u,_ in candidates),
            'alternative':-1,'required_context':[u['unit_id'] for _,u,_ in candidates]}
        candidates.append((len(terms & set(tokenize(text,'ko_bigram'))),unit,text))
    candidates.sort(key=lambda x: (-x[0], x[1].get('alternative', 0), x[1]['start']))
    return [(u, text) for _, u, text in candidates]


def reference_packet(index, query, max_chars=12000, top_k=5, audit=None):
    if max_chars < 2 or top_k < 1:
        raise ValueError('INVALID_PACKET_BUDGET')
    # Dedup AFTER a nonempty unit fits, so blank/oversized hits never fill a slot.
    hits = index.search(query, top_k=len(getattr(index, 'records', [])) or 100, deduplicate=False)
    rows, seen, excluded = [], set(), []
    for hit in hits:
        if len(rows) == top_k:
            break
        groups = set(hit.get('evidence_groups', hit['evidence_ids']))
        if groups & seen:
            excluded.append({'chunk_id': hit['chunk_id'], 'reason': 'DUPLICATE_SOURCE_GROUP'})
            continue
        allowed, reason = research_decision(hit)
        if not allowed:
            excluded.append({'chunk_id': hit['chunk_id'], 'reason': reason})
            continue
        source = hit.get('source_metadata', {})
        base = {'chunk_id': hit['chunk_id'], 'retrieval_rank_raw': hit.get('rank'),
            'document_id': hit['document_id'], 'case_id': hit.get('case_id'),
            'source_role': hit['source_role'], 'document_type': hit.get('document_type'), 'record_kind': hit['record_kind'],
            'title': hit['title'], 'issuer': hit.get('issuer'), 'source_page': hit['source_page'],
            'source_url': hit.get('source_url') or source.get('catalog_url'), 'source_sha256': hit.get('source_sha256'),
            'evidence_ids': hit['evidence_ids'], 'review_status': hit['review_status'],
            'historical_ai_review_status': hit.get('historical_ai_review_status'),
            'original_llm_processing_allowed': source.get('llm_processing_allowed'),
            'original_llm_processing_restriction': source.get('llm_processing_restriction'),
            'research_use': reason, 'external_submission_status': 'UNCONFIRMED',
            'license': hit.get('license'), 'not_current_patient_facts': True,
            'case_evidence_relation': 'SYNTHETIC_CASE_ASSOCIATION' if hit.get('case_id') else 'REFERENCE_CONTEXT',
            'use_as_universal_diagnostic_rule': False}
        candidates = evidence_candidates(index, hit, query)
        for unit, text in candidates:
            row = dict(base, text=text, text_scope=unit['scope'], unit_id=unit['unit_id'],
                unit_location={'parent_id': hit['parent_id'], 'start': unit['start'], 'end': unit['end'], 'field': unit['field']},
                unit_heading=unit.get('heading'), required_context=unit.get('required_context', []))
            if len(json.dumps(rows + [row], ensure_ascii=False)) <= max_chars:
                rows.append(row); seen |= groups
                break
        else:
            excluded.append({'chunk_id': hit['chunk_id'], 'reason': 'NO_COMPLETE_UNIT' if not candidates else 'COMPLETE_UNIT_OVER_BUDGET',
                'candidate_body_chars': [len(text) for _, text in candidates]})
    if audit is not None:
        audit.update(excluded=excluded, valid_evidence_count=len(rows), body_chars=sum(len(r['text']) for r in rows),
            packet_chars=len(json.dumps(rows, ensure_ascii=False)), budget=max_chars, requested_top_k=top_k,
            source_traceable=all(r['evidence_ids'] and r['document_id'] and r['unit_location'] for r in rows))
    return rows


def visible_facts(facts, max_chars=22000):
    initial = [f for f in facts if f['kind'] in ('opening', 'vitals')]
    selected = list(initial)
    others = [f for f in facts if f not in initial]
    early = [f for f in others if re.search(r'약|복용|항생제|알레르기|언제|시작|과거|수술|임신|기저', f.get('question') or '')]
    for f in early + list(reversed(others)):
        if f not in selected and len(json.dumps(selected + [f], ensure_ascii=False)) <= max_chars:
            selected.append(f)
    selected.sort(key=lambda f: int(f['id'][1:]))
    if len(json.dumps(selected, ensure_ascii=False)) > max_chars:
        raise ValueError('INITIAL_CONTEXT_TOO_LARGE')
    return selected
