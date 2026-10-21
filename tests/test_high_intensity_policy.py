"""Reject changes outside the explicit auxiliary Doctor-call exception."""
import socket
import unittest

import check_high_intensity as policy


class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = policy.HARNESS_MODULE
        cls.baseline = policy.BASELINE_LOOP_SOURCE
        if cls.h is None or cls.baseline is None:
            raise RuntimeError('RUN_WITH_CHECK_HIGH_INTENSITY_FOR_PINNED_BASELINE_AND_AUDIT_GUARD')
        cls.source = (policy.ROOT / 'app/nova_agent/loop.py').read_text(encoding='utf-8')
        cls.strategy = (policy.ROOT / 'app/nova_agent/clinical_strategy.py').read_text(encoding='utf-8')
        cls.config = (policy.ROOT / 'app/nova_agent/experiment_config.py').read_text(encoding='utf-8')

    def test_exact_exception_keeps_original_protected_symbols(self):
        policy.verify_loop(self.h, self.source, self.baseline)
        original = self.h.protected_signature(self.baseline, 'loop.py')
        changed = self.h.protected_signature(self.source, 'loop.py')
        self.assertEqual([name for name in original if original[name] != changed[name]], ['doctor'])
        policy.verify_new_modules(self.strategy, self.config)

    def test_model_budget_sdk_deadline_and_record_remain_protected(self):
        changes = (
            ("MODEL = 'openai/gpt-6-luna'", "MODEL = 'other-model'"),
            ('max_input_budget: int = 500000', 'max_input_budget: int = 500001'),
            ('max_doctor_requests: int = 80', 'max_doctor_requests: int = 81'),
            ("os.environ.get('NOVA_RAG_SOURCES', 'auto')", "os.environ.get('NOVA_RAG_SOURCES', 'none')"),
            ("'EXAM': self.client.exam", "'EXAM': self.client.say"),
            ('1800 - (time.monotonic() - self.started)', '1801 - (time.monotonic() - self.started)'),
        )
        for old, new in changes:
            with self.subTest(old=old):
                self.assertIn(old, self.source)
                with self.assertRaisesRegex(ValueError, 'PROTECTED_SYMBOL_CHANGE'):
                    policy.verify_loop(self.h, self.source.replace(old, new, 1), self.baseline)
        prompts = (policy.ROOT / 'app/nova_agent/prompts.py').read_text(encoding='utf-8')
        original = self.h.protected_signature(prompts, 'prompts.py')
        self.assertNotEqual(original, self.h.protected_signature(prompts.replace("RECORD = '''", "RECORD = '''unsafe "), 'prompts.py'))

    def test_transport_reservation_settlement_final_reserve_and_retry_cannot_drift(self):
        changes = (
            ('self.budget.reserve(', 'self.budget.unchecked_reserve('),
            ('self.budget.settle(', 'self.budget.skip_settle('),
            ('headroom = envelope.headroom()', 'headroom = (0, 0, 0)'),
            ('self.record_envelope.validate(system, user, ordinal)', 'self.record_envelope.validate(system, user, 0)'),
            ('max(envelope.charges) > 100000', 'max(envelope.charges) > 200000'),
        )
        for old, new in changes:
            with self.subTest(old=old):
                self.assertIn(old, self.source)
                with self.assertRaisesRegex(ValueError, 'DOCTOR_EXTENSION_OUTSIDE_EXACT_POLICY'):
                    policy.verify_loop(self.h, self.source.replace(old, new, 1), self.baseline)
        extra_call = self.source + '\ndef unbudgeted(client):\n    return client.chat([])\n'
        with self.assertRaisesRegex(ValueError, 'MODEL_CALL_OUTSIDE_PROTECTED_DOCTOR'):
            policy.verify_loop(self.h, extra_call, self.baseline)

    def test_file_scope_remains_narrower_than_original_candidate_policy(self):
        known = {'app/nova_agent/loop.py', 'app/nova_agent/prompts.py', 'app/nova_agent/budget.py', 'app/nova_sdk.py'}
        policy.verify_scope(self.h, sorted(policy.APP_CHANGES), known, {})
        for name in ('app/nova_sdk.py', 'app/nova_agent/budget.py', 'app/nova_agent/prompts.py',
                     'app/nova_agent/record.py', 'app/indexes/bm25_ko.json.gz', 'app/nova_agent/extra.py'):
            with self.subTest(path=name), self.assertRaisesRegex(ValueError, 'APP_SCOPE_VIOLATION'):
                policy.verify_scope(self.h, [name], known, {})
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_HARNESS_SCOPE'):
            policy.verify_scope(self.h, ['app/nova_agent/loop.py'], known, {'app/nova_agent/loop.py': 'SYMLINK'})

    def test_new_modules_cannot_change_default_or_add_unbudgeted_transport(self):
        with self.assertRaisesRegex(ValueError, 'DEFAULT_MUST_BE_BASELINE'):
            policy.verify_new_modules(self.strategy, "STRATEGY = 'H4'\n")
        with self.assertRaisesRegex(ValueError, 'DEFAULT_MUST_BE_BASELINE'):
            policy.verify_new_modules(self.strategy, self.config + '\nunsafe()\n')
        for method in ('chat', 'session', 'say', 'exam', 'diagnose'):
            with self.subTest(method=method), self.assertRaisesRegex(ValueError, 'TRANSPORT_OR_DYNAMIC_EXECUTION'):
                policy.verify_new_modules(self.strategy + '\ndef bypass(client):\n    return client.' + method + '()\n', self.config)

    def test_auxiliary_settings_do_not_unlock_high_or_raise_output_caps(self):
        changes = (
            ("return 3072, 'medium'", "return 8192, 'high'"),
            ("strategy == 'H4' and seconds_left > 300", 'seconds_left > 0'),
            ("'H2': ('examination',)", "'H2': ('examination', 'audit')"),
        )
        for old, new in changes:
            with self.subTest(change=old):
                self.assertIn(old, self.strategy)
                with self.assertRaisesRegex(ValueError, 'AUXILIARY_SETTINGS_OUTSIDE_EXACT_POLICY'):
                    policy.verify_new_modules(self.strategy.replace(old, new, 1), self.config)
        for old, new in (
            ('range(1 if auxiliary else cfg.attempts)', 'range(cfg.attempts)'),
            ("effort = 'medium'", "effort = 'high'"),
            ('self.left() - cfg.time_margin)', 'self.left())'),
            ("purpose not in ('ACTION', 'PLAN', 'AUDIT')", "purpose not in ('ACTION', 'PLAN', 'AUDIT', 'EXTRA')"),
        ):
            with self.subTest(change=old), self.assertRaisesRegex(ValueError, 'DOCTOR_EXTENSION_OUTSIDE_EXACT_POLICY'):
                policy.verify_loop(self.h, self.source.replace(old, new, 1), self.baseline)

    def test_existing_worker_guard_is_installed(self):
        # socket creation itself must be rejected; no address or request exists.
        with self.assertRaisesRegex(PermissionError, 'HARNESS_NETWORK'):
            with socket.socket():
                pass


if __name__ == '__main__':
    unittest.main()
