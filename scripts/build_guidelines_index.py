"""Offline build, outside prepare; accepts only a catalog-backed guideline root."""
import argparse
import collections
import csv
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from nova_retrieval.guidelines import FORMAT, header, terms, put_varint, safe_path


def build(root, output):
    root, output = Path(root), Path(output)
    if output.exists():
        raise FileExistsError('KEEP_EXISTING_INDEX')
    start = time.monotonic()
    catalog = root / 'catalog.csv'
    with catalog.open(encoding='utf-8-sig', newline='') as f:
        records = list(csv.DictReader(f))
    postings, last, dfs = {}, {}, collections.Counter()
    docs, langs, licenses, types, differences = [], collections.Counter(), collections.Counter(), collections.Counter(), []
    seen = set()
    for docid, row in enumerate(records, 1):
        relative = row['파일명']
        if relative in seen or not relative.endswith('.md'):
            raise ValueError('INVALID_CATALOG_PATH')
        seen.add(relative)
        raw = safe_path(root, relative).read_bytes()
        text = raw.decode('utf-8-sig')
        meta, start_body = header(text)
        for k, ck in [('title','제목'),('organization','발행기관'),('year','연도'),('source_url','출처 URL'),('license','라이선스')]:
            if meta[k] != row[ck]:
                differences.append({'path': relative, 'field': k})
        counts = collections.Counter(terms(meta['title'] + '\n' + text[start_body:]))
        for token, freq in counts.items():
            stream = postings.setdefault(token, bytearray())
            put_varint(stream, docid - last.get(token, 0))
            put_varint(stream, freq)
            last[token] = docid
            dfs[token] += 1
        meta.update(relative_path=relative, document_type=row['문서 유형'],
                    source_sha256=hashlib.sha256(raw).hexdigest())
        docs.append((docid, sum(counts.values()), json.dumps(meta, ensure_ascii=False)))
        langs[meta['language']] += 1; licenses[meta['license']] += 1; types[row['문서 유형']] += 1
        if docid % 2000 == 0:
            print(json.dumps({'indexed': docid, 'seconds': round(time.monotonic()-start, 1)}), flush=True)
    actual = {p.relative_to(root).as_posix() for p in root.glob('*/*.md')}
    if actual != seen:
        raise ValueError('CATALOG_DOCUMENT_SET_MISMATCH')
    output.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(output)
    db.executescript('PRAGMA journal_mode=OFF; CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);'
                    'CREATE TABLE documents(id INTEGER PRIMARY KEY,length INTEGER,metadata TEXT);'
                    'CREATE TABLE terms(token BLOB PRIMARY KEY,df INTEGER,posting BLOB) WITHOUT ROWID;')
    db.executemany('INSERT INTO documents VALUES(?,?,?)', docs)
    db.executemany('INSERT INTO terms VALUES(?,?,?)', ((t, dfs[t], bytes(p)) for t,p in sorted(postings.items())))
    info = {'format': FORMAT, 'catalog_sha256': hashlib.sha256(catalog.read_bytes()).hexdigest(),
            'documents': str(len(docs)), 'hash': 'blake2b-64', 'k1': '1.5', 'b': '0.75'}
    db.executemany('INSERT INTO metadata VALUES(?,?)', info.items())
    db.commit(); db.close()
    return {'documents': len(docs), 'languages': dict(langs), 'licenses': dict(licenses),
            'document_types': dict(types), 'header_catalog_differences': differences,
            'vocabulary': len(postings), 'seconds': time.monotonic()-start, 'bytes': output.stat().st_size,
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'body_stored': False,
            'catalog_sha256': info['catalog_sha256']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--root', required=True); p.add_argument('--output', required=True); p.add_argument('--report', required=True)
    a=p.parse_args(); result=build(a.root,a.output)
    Path(a.report).parent.mkdir(parents=True,exist_ok=True)
    Path(a.report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['licenses','header_catalog_differences']},ensure_ascii=True))
