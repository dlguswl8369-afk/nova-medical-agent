"""No API/model traffic: verify the bounded ledger and ambiguous-create path."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'app')]
import run_public_comparison as runner


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT.parent)
        self.out=Path(self.temp.name)/'runs'
        self.args=argparse.Namespace(output=str(self.out),remaining=5,credit_percent=99.5,
                                    no_active_samples=True,baseline='',samples='')
        self.key=patch.dict(os.environ,{'NOVA_DEV_KEY':'synthetic-test-key'});self.key.start()

    def tearDown(self):
        self.key.stop();self.temp.cleanup()

    def test_credit_and_remaining_gate_precedes_server_requests(self):
        with patch('nova_sdk.Client') as client:
            with self.assertRaisesRegex(ValueError,'REMAINING_CREDIT'):
                runner.main(self.args)
            client.return_value._request.assert_not_called()
        self.assertFalse((self.out/'comparison.lock').exists())

    def test_pending_create_reuses_request_id_then_stops(self):
        self.out.mkdir()
        names=[f'{code}_{v}.json' for code in runner.CASES for v in ('v3.2','v3.3')]
        runner.save(self.out/'comparison_ledger.json',{'purpose':runner.PURPOSE,'slots':names})
        runner.save(self.out/names[0],{'status':'CREATE_PENDING','case_uuid':'case-fixed',
                                     'create_request_id':'request-fixed'})
        with patch('nova_sdk.Client') as client,patch.object(runner.subprocess,'run') as child:
            client.return_value.create_sample.return_value={'session_id':'same-session','status':'active'}
            with self.assertRaisesRegex(RuntimeError,'EXISTING_SLOT_REQUIRES_REVIEW'):
                runner.main(self.args)
            client.return_value.create_sample.assert_called_once_with('case-fixed',request_id='request-fixed')
            child.assert_not_called()
        self.assertEqual(json.loads((self.out/names[0]).read_text())['session_id'],'same-session')

    def test_existing_active_session_is_queried_without_creating_another(self):
        self.out.mkdir()
        names=[f'{code}_{v}.json' for code in runner.CASES for v in ('v3.2','v3.3')]
        runner.save(self.out/'comparison_ledger.json',{'purpose':runner.PURPOSE,'slots':names})
        runner.save(self.out/names[0],{'status':'ACTIVE','session_id':'existing-session'})
        with patch('nova_sdk.Client') as client:
            client.return_value.session.return_value={'status':'active'}
            with self.assertRaisesRegex(RuntimeError,'EXISTING_SLOT_REQUIRES_REVIEW'):
                runner.main(self.args)
            client.return_value.session.assert_called_once()
            client.return_value.create_sample.assert_not_called()

    def test_private_output_cannot_enter_repository(self):
        self.args.output=str(ROOT/'private_runs')
        with self.assertRaisesRegex(ValueError,'OUTSIDE_REPOSITORY'):runner.main(self.args)


if __name__=='__main__':unittest.main()
