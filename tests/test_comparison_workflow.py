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
import review_public_comparison as reviewer
from summarize_public_comparison import collect


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

    def review_fixture(self):
        self.out.mkdir()
        samples=Path(self.temp.name)/'samples'
        for code in runner.CASES:
            (samples/code).mkdir(parents=True)
            runner.save(samples/code/'case.json',{'evaluator_only':'SYNTHETIC_TARGET'})
            for version in ('v3.2','v3.3'):
                runner.save(self.out/f'{code}_{version}.json',{'status':'completed'})
                runner.save(self.out/f'{code}_{version}_private.json',{'events':[],
                    'final':{'note':'SYNTHETIC_PRIVATE_NOTE'},'last_reference_context':{},'report':{}})
        return samples

    def test_review_has_three_requests_and_no_session_binding(self):
        samples=self.review_fixture()
        with patch.object(reviewer,'Client') as client:
            client.return_value.chat.return_value={'usage':{},'choices':[]}
            reviewer.run_reviews(self.out,samples,'synthetic-test-key')
            self.assertEqual(client.return_value.session_id,'')
            self.assertEqual(client.return_value.chat.call_count,3)
            reviewer.run_reviews(self.out,samples,'synthetic-test-key')
            self.assertEqual(client.return_value.chat.call_count,3)

    def test_uncertain_review_is_not_replaced(self):
        samples=self.review_fixture()
        with patch.object(reviewer,'Client') as client:
            client.return_value.chat.side_effect=TimeoutError()
            with self.assertRaises(TimeoutError):reviewer.run_reviews(self.out,samples,'synthetic-test-key')
            with self.assertRaisesRegex(RuntimeError,'PENDING_REVIEW'):
                reviewer.run_reviews(self.out,samples,'synthetic-test-key')
            self.assertEqual(client.return_value.chat.call_count,1)

    def test_review_requires_all_six_closed(self):
        samples=self.review_fixture()
        runner.save(self.out/'C03_v3.3.json',{'status':'ACTIVE'})
        with patch.object(reviewer,'Client') as client:
            with self.assertRaisesRegex(ValueError,'ALL_SIX'):
                reviewer.run_reviews(self.out,samples,'synthetic-test-key')
            client.assert_not_called()

    def test_public_summary_excludes_patient_text(self):
        self.review_fixture()
        text=json.dumps(collect(self.out))
        self.assertNotIn('SYNTHETIC_PRIVATE_NOTE',text)
        self.assertNotIn('SYNTHETIC_TARGET',text)


if __name__=='__main__':unittest.main()
