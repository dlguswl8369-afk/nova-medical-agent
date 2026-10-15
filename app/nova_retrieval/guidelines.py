"""Read-only BM25 over hashed postings; evidence is read from organizer originals.

The database contains document metadata, hashes, lengths and term frequencies,
not original bodies. Hashing terms is a storage choice, not a rights clearance.
"""
import collections
import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from .tokenize import tokenize

FORMAT = 'nova-guidelines-bm25-v1'
FIELDS = ('title', 'organization', 'year', 'language', 'source_url', 'license')


def terms(text):
    return [hashlib.blake2b(t.encode('utf-8'), digest_size=8).digest()
            for t in tokenize(text)]


def header(text):
    match = re.match(r'\A\ufeff?---\r?\n(.*?)\r?\n---(?:\r?\n|$)', text, re.S)
    if not match:
        raise ValueError('GUIDELINE_HEADER_REQUIRED')
    values = {}
    for line in match[1].splitlines():
        key, sep, value = line.partition(':')
        if sep and key in FIELDS:
            value = value.strip()
            if value.startswith('"'):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    value = value[1:-1].replace('\\"', '"')
            values[key] = value
    if any(k not in values for k in FIELDS):
        raise ValueError('GUIDELINE_METADATA_MISSING')
    return values, match.end()


def safe_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or Path(relative).is_absolute():
        raise ValueError('SOURCE_PATH_OUTSIDE_ROOT')
    return path


def canonical_url(value):
    parts = urlsplit(value or '')
    host = (parts.hostname or '').lower().removeprefix('www.')
    path = re.sub(r'/index\.html?$', '', parts.path.rstrip('/')).rstrip('/')
    return urlunsplit(('', host, path, parts.query, '')) if host else ''


def identities(row):
    ids = set()
    url = canonical_url(row.get('source_url'))
    if url:
        ids.add(('url', url))
    if row.get('source_sha256'):
        ids.add(('sha256', row['source_sha256']))
    title = re.sub(r'\W+', '', str(row.get('title', '')).casefold())
    if title:
        ids.add(('title', title))
    return ids


def put_varint(out, value):
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)


def read_varints(blob):
    value = shift = 0
    for byte in blob:
        value |= (byte & 127) << shift
        if byte < 128:
            yield value
            value = shift = 0
        else:
            shift += 7
    if shift:
        raise ValueError('CORRUPT_POSTING')


def complete_sections(text, body_start):
    # H2 includes all nested lists/H3 exceptions. Never split a paragraph to fit.
    marks = list(re.finditer(r'^## (.+)$', text[body_start:], re.M))
    if not marks:
        return [(body_start, len(text), 'COMPLETE_DOCUMENT_BODY')]
    return [(body_start + mark.start(),
             body_start + marks[i + 1].start() if i + 1 < len(marks) else len(text),
             mark[1].strip()) for i, mark in enumerate(marks)]


class GuidelinesIndex:
    def __init__(self, database, root):
        self.root = Path(root).resolve()
        self.db = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
        self.db.execute('PRAGMA query_only=ON')
        self.db.execute('PRAGMA cache_size=-8192')
        self.meta = dict(self.db.execute('SELECT key,value FROM metadata'))
        if self.meta['format'] != FORMAT:
            self.db.close()
            raise ValueError('GUIDELINE_INDEX_FORMAT')
        catalog = self.root / 'catalog.csv'
        if not catalog.is_file() or hashlib.sha256(catalog.read_bytes()).hexdigest() != self.meta['catalog_sha256']:
            self.db.close()
            raise ValueError('GUIDELINE_CATALOG_MISMATCH')
        self.lengths = dict(self.db.execute('SELECT id,length FROM documents'))
        self.count = len(self.lengths)
        self.average = sum(self.lengths.values()) / max(1, self.count)

    def close(self):
        self.db.close()

    def search(self, query, top_k=40):
        scores = collections.defaultdict(float)
        query_terms = list(dict.fromkeys(terms(query)))
        # Query is already budgeted by query_from_facts; retain all terms, including negatives.
        for term in query_terms:
            row = self.db.execute('SELECT df,posting FROM terms WHERE token=?', (term,)).fetchone()
            if not row:
                continue
            df, blob = row
            idf = math.log(1 + (self.count - df + .5) / (df + .5))
            values = iter(read_varints(blob))
            doc = 0
            for delta, freq in zip(values, values):
                doc += delta
                norm = 1.5 * (.25 + .75 * self.lengths[doc] / self.average)
                scores[doc] += idf * freq * 2.5 / (freq + norm)
        rows = []
        for rank, (doc, score) in enumerate(sorted(scores.items(), key=lambda p: (-p[1], p[0]))[:top_k], 1):
            meta = json.loads(self.db.execute('SELECT metadata FROM documents WHERE id=?', (doc,)).fetchone()[0])
            rows.append(dict(meta, rank=rank, score=score))
        return rows

    def evidence(self, hit, query):
        raw = safe_path(self.root, hit['relative_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != hit['source_sha256']:
            raise ValueError('GUIDELINE_SOURCE_HASH_MISMATCH')
        text = raw.decode('utf-8-sig')
        meta, start = header(text)
        wanted = set(terms(query))
        spans = complete_sections(text, start)
        spans.sort(key=lambda span: (-len(wanted.intersection(terms(text[span[0]:span[1]]))), span[0]))
        for begin, end, heading in spans:
            body = text[begin:end]
            if not body.strip() or not wanted.intersection(terms(body)):
                continue
            unit = hit['relative_path'] + ':' + str(begin) + ':' + str(end)
            yield {'chunk_id': unit, 'unit_id': unit, 'document_id': hit['relative_path'],
                   'title': meta['title'], 'issuer': meta['organization'], 'year': meta['year'],
                   'language': meta['language'], 'source_url': meta['source_url'], 'license': meta['license'],
                   'document_type': hit['document_type'], 'source_role': 'organizer_guideline',
                   'source_sha256': hit['source_sha256'], 'source_page': None,
                   'evidence_ids': [unit], 'text': body, 'text_scope': 'COMPLETE_H2_OR_DOCUMENT',
                   'unit_heading': heading, 'relative_path': hit['relative_path'],
                   'unit_location': {'parent_id': hit['relative_path'], 'start': begin, 'end': end, 'field': 'markdown'},
                   'not_current_patient_facts': True, 'use_as_universal_diagnostic_rule': False,
                   'external_submission_status': 'DOCUMENT_SPECIFIC_CONDITIONS_NOT_BLANKET_CLEARANCE',
                   'retrieval_rank_raw': hit['rank'], 'research_use': 'ORGANIZER_NONCOMMERCIAL_SCOPE'}


class CombinedIndex:
    def __init__(self, legacy=None, guidelines=None):
        self.legacy, self.guidelines = legacy, guidelines

    def search(self, query, top_k=5):
        candidates=[]
        if self.legacy is not None:
            candidates.extend((r['rank'],'legacy',r) for r in self.legacy.search(query,top_k=top_k*2))
        if self.guidelines is not None:
            candidates.extend((r['rank'],'guidelines',r) for r in self.guidelines.search(query,top_k=top_k*2))
        rows=[];seen=set()
        for _,source,row in sorted(candidates,key=lambda r:(r[0],r[1])):
            keys=identities(row)
            if keys & seen:continue
            rows.append(dict(row,rank=len(rows)+1,retrieval_source=source))
            seen.update(keys)
            if len(rows)==top_k:break
        return rows

    def packet(self, query, max_chars=12000, top_k=5, audit=None):
        from nova_agent.context import reference_packet
        candidates = []
        if self.legacy is not None:
            # Keep legacy policy gating and intact-unit behavior unchanged.
            candidates.extend((i, 'legacy', row) for i, row in enumerate(
                reference_packet(self.legacy, query, max_chars, top_k=top_k * 3), 1))
        excluded = []
        if self.guidelines is not None:
            for hit in self.guidelines.search(query, top_k=40):
                found = False
                for row in self.guidelines.evidence(hit, query):
                    if len(json.dumps([row], ensure_ascii=False)) <= max_chars:
                        candidates.append((hit['rank'], 'guidelines', row))
                        found = True
                        break
                if not found:
                    excluded.append({'reason': 'NO_COMPLETE_UNIT_WITHIN_BUDGET'})
        # Interleave rank positions, not incompatible raw BM25 scores.
        candidates.sort(key=lambda item: (item[0], item[1]))
        rows, seen = [], set()
        for _, _, row in candidates:
            keys = identities(row)
            if keys & seen:
                excluded.append({'reason': 'DUPLICATE_SOURCE_IDENTITY'})
                continue
            if len(json.dumps(rows + [row], ensure_ascii=False)) > max_chars:
                excluded.append({'reason': 'COMPLETE_UNIT_OVER_BUDGET'})
                continue
            rows.append(row)
            seen.update(keys)
            if len(rows) == top_k:
                break
        if audit is not None:
            audit.update(excluded=excluded, valid_evidence_count=len(rows),
                         body_chars=sum(len(r['text']) for r in rows),
                         packet_chars=len(json.dumps(rows, ensure_ascii=False)), budget=max_chars,
                         requested_top_k=top_k, source_traceable=True)
        return rows
