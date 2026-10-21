"""Only gaps introduced by the harness; clinical contracts reuse existing tests."""
import copy
import json
from pathlib import Path
import socket
import unittest

from dev_harness import ROOT, BASELINES, guard_event, scope_status, validate_case, protected_signature


class HarnessTests(unittest.TestCase):
    def test_candidate_cannot_change_model_or_record_through_editable_files(self):
        loop_path = 'app/nova_agent/loop.py'
        source = (ROOT / loop_path).read_text(encoding='utf-8')
        original = protected_signature(source, loop_path)
        self.assertEqual(original, protected_signature(source + '\n# harmless comment\n', loop_path))
        for changed in (source.replace('openai/gpt-6-luna', 'different-model'),
                        source.replace("'medium'", "'low'")):
            self.assertNotEqual(original, protected_signature(changed, loop_path))
        prompts_path = 'app/nova_agent/prompts.py'
        prompts = (ROOT / prompts_path).read_text(encoding='utf-8')
        self.assertNotEqual(protected_signature(prompts, prompts_path),
                            protected_signature(prompts.replace("RECORD = '''", "RECORD = '''changed "), prompts_path))

    def test_explicit_candidate_scope_cannot_unlock_protected_code(self):
        known = {'app/nova_agent/prompts.py', 'app/nova_agent/budget.py', 'app/nova_sdk.py'}
        self.assertEqual(scope_status([], known), 'PASS')
        self.assertEqual(scope_status(['app/nova_agent/prompts.py'], known), 'FAIL')
        self.assertEqual(scope_status(['app/nova_agent/prompts.py', 'app/nova_agent/coverage.py'], known, True), 'REVIEW')
        for protected in ('app/nova_sdk.py', 'app/nova_agent/budget.py', 'app/indexes/new.json'):
            self.assertEqual(scope_status([protected], known, True), 'FAIL')
        self.assertEqual(BASELINES['v3.5'], '81714d340207a8e5ca9886dd2129cbd6b9cc61f2')

    def test_network_process_and_external_write_audit_rules(self):
        allowed = ROOT / 'reports/harness_runs/synthetic'
        for event, args in [('socket.connect', (None, ('example.invalid', 443))),
                            ('subprocess.Popen', ('python', [], None, None)), ('os.system', ('echo test',)),
                            ('open', (str(ROOT / 'app/nova_sdk.py'), 'w', 0)),
                            ('os.remove', (str(ROOT / 'app/nova_sdk.py'), -1)),
                            ('os.rename', (str(allowed / 'a'), str(ROOT / 'app/a'), -1, -1))]:
            with self.subTest(event=event), self.assertRaises(PermissionError):
                guard_event(event, args, allowed)
        guard_event('open', (str(ROOT / 'app/nova_sdk.py'), 'r', 0), allowed)
        guard_event('open', (str(allowed / 'result.json'), 'w', 0), allowed)

    def test_worker_audit_hook_is_actually_installed(self):
        # No address or network operation even if the guard regresses.
        with self.assertRaisesRegex(PermissionError, 'HARNESS_NETWORK'):
            with socket.socket():
                pass

    def test_cases_require_evidence_and_never_certify_quality(self):
        example = json.loads((ROOT / 'harness/cases/example.json').read_text(encoding='utf-8'))
        self.assertEqual(validate_case(example)['clinical_quality'], 'NOT_EVALUATED')
        for change, error in [('missing', 'EVIDENCE_REQUIRED'), ('wrong', 'UNKNOWN_EVIDENCE'), ('leak', 'DOCTOR_INPUT_ALLOWLIST')]:
            case = copy.deepcopy(example)
            if change == 'leak':
                case['doctor_input']['reference_record'] = 'not a patient observation'
            else:
                case['criteria'][0]['status'] = 'PASS'
                case['criteria'][0]['evidence'] = [] if change == 'missing' else [{'source': 'trace', 'id': 'missing'}]
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, error):
                validate_case(case)
        case = copy.deepcopy(example)
        case['criteria'][0].update(status='REVIEW', evidence=[{'source': 'trace', 'id': 'T1'}])
        self.assertEqual(validate_case(case)['clinical_quality'], 'NOT_EVALUATED')
