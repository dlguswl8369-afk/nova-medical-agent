"""Construct a separate search corpus without changing source data or judgments."""
import collections
import hashlib
import os
import re
from pathlib import Path
from .common import read_jsonl, write_json, write_jsonl, digest


def split_spans(text, target=1400):
    """Soft size limit: blank-line boundaries, never cut a list/condition block.

    Three adjacent blocks overlap for headings and antecedents; the complete parent
    remains retrievable. Oversize blocks are deliberately kept intact.
    """
    if len(text) <= target:
        return [(0, len(text))]
    blocks = list(re.finditer(r"[^\n](?:.*?)(?=\n\s*\n|\Z)", text, re.S))
    if not blocks:
        return [(0, len(text))]
    spans, i = [], 0
    while i < len(blocks):
        j = i + 1
        while j < len(blocks) and blocks[j].end() - blocks[i].start() <= target:
            j += 1
        # Do not leave a short heading detached from its following content.
        if j < len(blocks) and len(blocks[j - 1].group().strip()) < 90:
            j += 1
        spans.append((blocks[i].start(), blocks[j - 1].end()))
        i = max(i + 1, j - 3) if j < len(blocks) else j
    return spans


def case_sections(case):
    text = case["case_text"]
    # Layout extraction can place a row label after its content. Return a broad
    # verbatim region starting at the final diagnosis table, with explicit status.
    start = re.search(r"최종\s*진단", text)
    tail = text[start.start():] if start else text
    end = re.search(r"적용\s*지침", tail)
    reason = tail[:end.start()] if end else tail
    return {
        "context": case["case_context_before_final_diagnosis"],
        "context_status": case["context_extraction_status"],
        "context_contains_source_title_and_in_course_diagnoses": True,
        "final_diagnosis_and_coding": case["diagnosis_coding_rows"],
        "final_diagnosis_excerpt": case["diagnosis_and_coding_excerpt"],
        "coding_rationale": reason,
        "coding_rationale_status": "BROAD_VERBATIM_REGION_INCLUDES_DIAGNOSIS_TABLE_PENDING_LAYOUT_REVIEW",
        "full_case_text": text,
    }


def prepare(data_dir, output_dir, chunk_chars=1400):
    data_dir, output_dir = Path(data_dir), Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing corpus: {output_dir}")
    if chunk_chars < 200:
        raise ValueError("chunk_chars must be >= 200")
    names = ["research/coding_cases", "research/source_chunks", "research/corrected_items", "evidence/source_assertions", "evidence/sources"]
    tables = {name: read_jsonl(data_dir / (name + ".jsonl")) for name in names}
    evidence = {r["assertion_id"]: r for r in tables["evidence/source_assertions"]}
    sources = {r["document_id"]: r for r in tables["evidence/sources"]}
    if len(evidence) != len(tables["evidence/source_assertions"]):
        raise ValueError("Duplicate assertion IDs")
    parents, records, excluded = {}, [], []
    cases = tables["research/coding_cases"]
    page_to_case = collections.defaultdict(list)
    for case in cases:
        for eid in case["evidence_ids"]:
            page_to_case[eid].append(case["case_id"])
    all_corrected = tables["research/corrected_items"]
    duplicate_aliases = collections.defaultdict(list)
    for item in all_corrected:
        if item.get("exclude_as_duplicate"):
            duplicate_aliases[item["canonical_item_id"]].append(item["item_id"])
    page_lookup = {(r["document_id"], r.get("source_page")): r["assertion_id"] for r in evidence.values() if r["assertion_id"].startswith("page:")}

    def make_record(raw, kind, rid, text, document_id, pages, eids):
        for eid in eids + raw.get("requires_context_evidence_ids", []):
            if eid not in evidence:
                raise ValueError(f"Missing evidence {eid} in {rid}")
        src = sources[document_id]
        links = []
        if kind == "coding_case":
            links = [{"disease_id": None, "candidate_disease_ids": raw["candidate_disease_ids"], "name": row["diagnosis_text"], "codes": row["codes"], "status": raw["code_link_status"]} for row in raw["diagnosis_coding_rows"]]
        elif kind == "corrected_item":
            links = [{"disease_id": raw.get("disease_id"), "name": raw.get("source_disease_name"), "codes": [evidence[e]["kcd_code"] for e in eids if evidence[e].get("kcd_code")], "status": raw.get("mapping_status")}]
        # Group underlying document pages, not assertion IDs, to avoid counting a
        # derived item, a case, and a page as independent supporting evidence.
        groups = [f"{document_id}:page:{p}" for p in pages] or [f"{document_id}:html"]
        parent_id = raw.get("parent_item_id") or rid
        return {
            "chunk_id": rid, "parent_id": parent_id, "text": text,
            "document_id": document_id, "case_id": raw.get("case_id"),
            "title": src["title"], "issuer": src["issuer"], "document_type": src["source_type"],
            "version": src.get("version"), "classification_version": raw.get("source_classification_version", raw.get("classification_version", src.get("classification_version"))),
            "source_role": raw.get("source_role", src["source_type"]),
            "source_page": pages[0] if len(pages) == 1 else (pages or None),
            "source_section": raw.get("source_section"), "source_url": src.get("source_url"),
            "source_sha256": src["sha256"], "license": src.get("license"),
            "external_redistribution_allowed": src.get("external_redistribution_allowed"),
            "record_kind": kind, "purpose": "case_based_reasoning" if kind == "coding_case" else raw.get("claim_type", "source_text_retrieval"),
            "evidence_ids": eids, "evidence_groups": groups,
            "requires_context_evidence_ids": raw.get("requires_context_evidence_ids", []),
            "disease_links": links, "review_status": raw["review_status"],
            "historical_ai_review_status": raw.get("historical_ai_review_status"),
            "expert_approved": raw.get("expert_approved", False),
            "use_as_universal_diagnostic_rule": False,
            "original_text": text, "processing": "VERBATIM; original source extraction retained",
            "original_record_id": rid, "canonical_item_id": raw.get("canonical_item_id"),
            "duplicate_alias_ids": duplicate_aliases[rid],
            "source_metadata": src,
        }

    for case in cases:
        record = make_record(case, "coding_case", case["case_id"], case["case_text"], case["document_id"], case["source_pages"], case["evidence_ids"])
        record["case_sections"] = case_sections(case)
        record["case_is_synthetic"] = case["case_is_synthetic"]
        parents[record["chunk_id"]] = record
        # Cases stay whole so symptoms, tests, evolution and exceptions stay joined.
        records.append(record.copy())
    for page in tables["research/source_chunks"]:
        rid = page["chunk_id"]
        pages = [page["source_page"]] if page["source_page"] is not None else []
        record = make_record(page, "source_page", rid, page["text"], page["document_id"], pages, page["evidence_ids"])
        record["related_case_ids"] = sorted({c for e in page["evidence_ids"] for c in page_to_case[e]})
        parents[rid] = record
        if record["related_case_ids"]:
            excluded.append({"id": rid, "reason": "PAGE_REPRESENTED_BY_FULL_CASE", "representatives": record["related_case_ids"]})
            continue
        for i, (start, end) in enumerate(split_spans(page["text"], chunk_chars)):
            child = record.copy()
            child.update(chunk_id=f"{rid}:{i}", text=page["text"][start:end], original_text=page["text"][start:end], source_span={"start": start, "end": end}, processing="VERBATIM_PARAGRAPH_WINDOW; soft size cap; 3-block overlap; full parent retrievable")
            records.append(child)
    for item in all_corrected:
        rid = item["item_id"]
        ev = evidence[item["evidence_ids"][0]]
        pages = [ev["source_page"]] if ev.get("source_page") is not None else []
        record = make_record(item, "corrected_item", rid, item["text"], ev["document_id"], pages, item["evidence_ids"])
        record["original_record"] = item
        record["evidence_locations"] = [evidence[e] for e in item["evidence_ids"]]
        # Parent retention is audit/context only; exclusions never enter postings.
        parents[rid] = record
        if item["review_status"] == "REJECTED" or item.get("historical_ai_review_status") == "REJECTED":
            excluded.append({"id": rid, "reason": "REJECTED"})
        elif item.get("exclude_as_duplicate"):
            excluded.append({"id": rid, "reason": "EXPLICIT_DUPLICATE", "representatives": [item["canonical_item_id"]]})
        elif item.get("is_container"):
            excluded.append({"id": rid, "reason": "CONTAINER_REPRESENTED_BY_CHILDREN"})
        else:
            records.append(record)
    # Exact duplicate text within a source is one searchable record; aliases remain.
    seen, deduped = {}, []
    for record in records:
        key = (record["document_id"], hashlib.sha256(record["text"].encode()).hexdigest())
        if key in seen:
            seen[key]["duplicate_alias_ids"].append(record["chunk_id"])
            excluded.append({"id": record["chunk_id"], "reason": "EXACT_TEXT_DUPLICATE", "representatives": [seen[key]["chunk_id"]]})
        else:
            seen[key] = record
            deduped.append(record)
    if len({r["chunk_id"] for r in deduped}) != len(deduped):
        raise ValueError("Duplicate search IDs")
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "records.jsonl", deduped)
    write_json(output_dir / "parents.json", parents)
    # All assertions remain a lookup/audit resource, never blindly indexed.
    write_json(output_dir / "evidence.json", evidence)
    report = {"input_counts": {k: len(v) for k, v in tables.items()}, "input_sha256": {n: digest(data_dir / (n + ".jsonl")) for n in names}, "search_records": len(deduped), "kinds": dict(collections.Counter(r["record_kind"] for r in deduped)), "roles": dict(collections.Counter(r["source_role"] for r in deduped)), "exclusion_counts": dict(collections.Counter(r["reason"] for r in excluded)), "exclusions": excluded, "chunk_chars_soft_target": chunk_chars, "max_chunk_chars": max(len(r["text"]) for r in deduped), "rejected_original_pages_policy": "REJECTED derived assertions excluded. Independently supplied source pages retained as unvalidated source text, not re-approved claims.", "guidelines_dir_configured": os.environ.get("NOVA_GUIDELINES_DIR"), "official_guidelines_ingested": False}
    write_json(output_dir / "preparation_report.json", report)
    return report
