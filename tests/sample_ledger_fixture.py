"""Two entirely synthetic prior records; never copies or writes the real ledger."""
import hashlib
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def setup_ledger(root):
    path=root/'original_v2/reports/public_session_budget.json';path.parent.mkdir(parents=True)
    data={'limit':3,'attempts':[{'case_id':'synthetic-'+str(i),'request_id':'prior-'+str(i),
        'time':'synthetic','extra':{'preserved':i}} for i in (1,2)]}
    path.write_text(json.dumps(data),encoding='utf-8');(root/'reports').mkdir(exist_ok=True)
    anchor={'version':1,'purpose':'final_development_sample','canonical_path':str(path.resolve()),
        'expected_attempts':2,'additional_attempts':1,'total_limit':3,
        'history_sha256':hashlib.sha256(json.dumps(data['attempts'],sort_keys=True).encode()).hexdigest(),
        'entry_sha256':[hashlib.sha256(json.dumps(a,sort_keys=True).encode()).hexdigest() for a in data['attempts']]}
    (root/'reports/final_sample_authorization.json').write_text(json.dumps(anchor),encoding='utf-8')
    return path

@contextmanager
def approved_ledger(runner):
    work=ROOT/'validation';work.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work) as name,patch.object(runner,'ROOT',Path(name)):
        yield setup_ledger(Path(name))
