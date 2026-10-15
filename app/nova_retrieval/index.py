import collections
import json
import math
import time
from pathlib import Path
from .common import load_gzip, save_gzip, read_jsonl
from .tokenize import tokenize


class BM25Index:
    """Okapi BM25, positive Robertson IDF, k1=1.5, b=0.75.

    Files are plain gzip JSON, never executable pickle; no network dependency.
    search() scores all matching records before deduplication and top-k selection.
    """
    def __init__(self, payload):
        if payload.get("format") != "nova-bm25-v1":
            raise ValueError("Unsupported local index format; rebuild using run.py build")
        self.payload = payload
        self.records = payload["records"]
        self.parents = payload["parents"]
        self.evidence = payload["evidence"]
        self.postings = payload["postings"]
        self.lengths = payload["lengths"]
        self.avgdl = sum(self.lengths) / max(1, len(self.lengths))

    @classmethod
    def build(cls, corpus_dir, output, tokenizer="ko_bigram"):
        started = time.perf_counter()
        corpus_dir = Path(corpus_dir)
        records = read_jsonl(corpus_dir / "records.jsonl")
        if not records:
            raise ValueError("Cannot build an empty corpus")
        lengths, postings = [], collections.defaultdict(list)
        for i, record in enumerate(records):
            counts = collections.Counter(tokenize(record["text"], tokenizer))
            lengths.append(sum(counts.values()))
            for term, tf in counts.items():
                postings[term].append([i, tf])
        payload = {"format": "nova-bm25-v1", "tokenizer": tokenizer, "k1": 1.5, "b": 0.75, "records": records, "parents": json.loads((corpus_dir / "parents.json").read_text(encoding="utf-8")), "evidence": json.loads((corpus_dir / "evidence.json").read_text(encoding="utf-8")), "lengths": lengths, "postings": dict(postings)}
        if Path(output).exists():
            raise FileExistsError(f"Refusing to overwrite index: {output}")
        save_gzip(output, payload)
        return {"build_seconds": time.perf_counter() - started, "records": len(records), "vocabulary": len(postings), "index_bytes": Path(output).stat().st_size, "tokenizer": tokenizer}

    @classmethod
    def load(cls, path):
        return cls(load_gzip(path))

    def get_parent(self, parent_id):
        return self.parents[parent_id]

    def get_evidence(self, evidence_id):
        return self.evidence[evidence_id]

    def search(self, question, top_k=5, source_roles=None, deduplicate=True, include_parent=False):
        if not isinstance(top_k, int) or top_k < 1:
            raise ValueError("top_k must be a positive integer")
        if isinstance(source_roles, str):
            source_roles = [source_roles]
        roles = set(source_roles or [])
        known = {r["source_role"] for r in self.records}
        if roles - known:
            raise ValueError(f"Unknown source roles {sorted(roles - known)}; choices: {sorted(known)}")
        scores = collections.defaultdict(float)
        n, k1, b = len(self.records), self.payload["k1"], self.payload["b"]
        # Query term multiplicity does not give repeated wording extra votes.
        for term in sorted(set(tokenize(question, self.payload["tokenizer"]))):
            posting = self.postings.get(term, [])
            if not posting:
                continue
            idf = math.log1p((n - len(posting) + 0.5) / (len(posting) + 0.5))
            for i, tf in posting:
                if roles and self.records[i]["source_role"] not in roles:
                    continue
                scores[i] += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * self.lengths[i] / self.avgdl))
        order = sorted(scores, key=lambda i: (-scores[i], self.records[i]["chunk_id"]))
        output, used = [], set()
        for i in order:
            record = self.records[i]
            groups = set(record["evidence_groups"])
            if deduplicate and used.intersection(groups):
                continue
            used.update(groups)
            result = dict(record, rank=len(output) + 1, score=scores[i])
            # Do not promote all sibling IDs into evidence_ids of a matched chunk.
            # Parent text is available separately and is not counted by evaluation.
            if include_parent:
                result["parent_context"] = self.get_parent(record["parent_id"])
            output.append(result)
            if len(output) >= top_k:
                break
        return output
