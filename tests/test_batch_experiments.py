"""Independent feature mechanics, not model competence or clinical scores."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nova_agent import loop
from nova_agent.context import fact, visible_facts, reference_packet
from nova_agent.experiments import FLAGS, action_view, action_prompt, clinical_packet
from nova_agent.prompts import STEP
from nova_retrieval.guidelines import GuidelinesIndex, CombinedIndex
from build_guidelines_index import build
from test_agent import NoResults, MockClient, plan
from test_simple_v35 import Replies, say


def unpack(value):
    table = value['current_patient_observations']
    if isinstance(table, list):
        return table
    return [dict((table['columns'][i], row[i]) for i in present)
            for row, present in zip(table['rows'], table['present'])]


def row(uid, text='복통 통증 문진 진찰 평가. 조건과 예외를 보존.', role='CLINICAL_GUIDELINE'):
    return {'unit_id': uid, 'document_id': uid, 'text': text, 'unit_heading': '평가',
            'source_role': role, 'source_sha256': 'synthetic-hash', 'evidence_ids': [uid],
            'unit_location': {'parent_id': uid, 'start': 0, 'end': len(text), 'field': 'text'},
            'text_scope': 'COMPLETE_H2_OR_DOCUMENT', 'not_current_patient_facts': True,
            'required_context': ['whole-section-including-exceptions'], 'source_url': 'https://example.invalid/' + uid}


class BatchTests(unittest.TestCase):
    def test_feature_matrix_and_v0_identity(self):
        self.assertEqual(FLAGS, {'V0': (), 'V1': ('rag',), 'V2': ('interview',),
                                'V3': ('communication',), 'V4': ('rag', 'interview', 'communication')})
        value = {'current_patient_observations': []}
        for strategy in ('V0', 'V1'):
            self.assertEqual(action_view(value, strategy), value)
            self.assertEqual(action_prompt(STEP, strategy), STEP)
        with self.assertRaises(ValueError):
            loop.Run(None, loop.State(NoResults(), strategy='typo'), {})

    def test_all_versions_use_real_loop_without_extra_model_calls_or_changed_record(self):
        records = []
        for strategy in FLAGS:
            c = Replies([say('복용약과 알레르기가 있나요?'), {'action': 'EXAM', 'content': '복부 압통 확인'},
                         say('검사 필요성을 설명드릴게요', 'EXPLAIN'), {'action': 'DONE'}, plan()],
                        ['약은 먹어요. 이름은 몰라요.', '무슨 뜻인가요?'])
            s = loop.State(NoResults(), loop.Config(retry_delay=0), strategy=strategy)
            loop.consult(c, s)
            contexts = [json.loads(p[1]['content']) for p in c.prompts]
            self.assertIsInstance(contexts[-1]['current_patient_observations'], list)
            self.assertEqual(c.chat_number, 5)
            self.assertEqual(s.report['termination_reason'], 'DOCTOR_DONE')
            self.assertFalse(s.report['patient_understanding_assessed'])
            self.assertEqual(s.report['acknowledged_explanations'], 1)
            self.assertEqual(unpack(contexts[-2])[-1]['id'] if strategy in ('V0', 'V1') else
                             {f['id'] for f in unpack(contexts[-2])},
                             'F4' if strategy in ('V0', 'V1') else {'F0', 'F1', 'F2', 'F3', 'F4'})
            records.append({k: c.submissions[0][k] for k in ('note', 'diagnosis')})
            self.assertEqual(c.prompts[0][0]['content'], action_prompt(STEP, strategy))
            self.assertIn('약은 먹어요. 이름은 몰라요.', json.dumps(records[-1], ensure_ascii=False))
            self.assertIn('무슨 뜻인가요?', json.dumps(records[-1], ensure_ascii=False))
        self.assertTrue(all(r == records[0] for r in records))

    def test_table_is_lossless_and_communication_only_deduplicates_visible_speech(self):
        facts = [fact('F0', 'opening', '위험을 시사하는 합성 원문'), fact('F1', 'vitals', '제공 활력'),
                 dict(fact('F2', 'patient_reply', '모르겠어요', '약 이름은 무엇인가요?'), intent='ASK'),
                 dict(fact('F3', 'exam', '실제 관찰', '복부 진찰'), intent='EXAM'),
                 dict(fact('F4', 'patient_reply', '운전해도 되나요?', '약 확인이 필요해요'), intent='EXPLAIN')]
        value = {'current_patient_observations': facts, 'doctor_explanations_already_sent': ['약 확인이 필요해요']}
        original = copy.deepcopy(value)
        for strategy in ('V2', 'V3', 'V4'):
            view = action_view(value, strategy)
            self.assertEqual(sorted(unpack(view), key=lambda f: f['id']), facts)
            self.assertEqual(len(view['current_patient_observations']['rows']), len(facts))
            self.assertEqual('doctor_explanations_already_sent' in view, strategy == 'V2')
        value['doctor_explanations_already_sent'].insert(0, '문맥에서 생략된 과거 설명')
        self.assertIn('doctor_explanations_already_sent', action_view(value, 'V4'))
        self.assertEqual(value['current_patient_observations'], original['current_patient_observations'])
        facts[-1]['future_field'] = 'must not silently drop'
        self.assertEqual(action_view(value, 'V4'), value)

    def test_no_observation_displacement_or_rewriting_at_budget_boundary(self):
        facts = [fact('F0', 'opening', '합성 위험 증상'), fact('F1', 'vitals', '활력')]
        facts += [fact(f'F{i}', 'patient_reply', '모름/부분 답변' * 35, '약을 복용하나요?') for i in range(2, 9)]
        baseline = visible_facts(facts, 1000)
        for strategy in ('V2', 'V3', 'V4'):
            view = action_view({'current_patient_observations': baseline}, strategy)
            self.assertEqual(sorted(unpack(view), key=lambda f: f['id']), baseline)
            self.assertIn('합성 위험 증상', json.dumps(view, ensure_ascii=False))

    def test_rag_adds_only_whole_topical_clinical_units_without_losing_baseline(self):
        base = [row('base', '기존 근거 AND 조건 OR 예외', 'CODING_GUIDELINE')]
        extra = row('new')
        original = copy.deepcopy(base)
        with patch('nova_agent.experiments.reference_packet', return_value=[extra, row('coding', role='CODING_EXAMPLES')]):
            packet, audit = clinical_packet(None, '복통 통증', base, 12000)
        self.assertEqual(packet, [extra] + original)
        self.assertEqual(base, original)
        self.assertEqual(audit['added_ids'], ['new'])
        self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False)), 12000)
        self.assertEqual(packet[0]['required_context'], extra['required_context'])

    def test_rag_fallback_and_full_packet_keep_every_baseline_field(self):
        base = [row('base', '코딩 전용', 'CODING_GUIDELINE')]
        invalid = row('invalid'); invalid.pop('source_sha256')
        for candidates in ([], [invalid], [row('unrelated', '전혀 무관')], [row('case', role='CODING_EXAMPLES')]):
            with patch('nova_agent.experiments.reference_packet', return_value=candidates):
                self.assertEqual(clinical_packet(None, '복통 통증', base, 12000)[0], base)
        with patch('nova_agent.experiments.reference_packet', side_effect=ValueError('HASH_MISMATCH')):
            self.assertEqual(clinical_packet(None, '복통 통증', base, 12000)[0], base)
        full = base + [row(str(i)) for i in range(4)]
        with patch('nova_agent.experiments.reference_packet') as search:
            packet, audit = clinical_packet(None, '복통 통증', full, 12000)
            search.assert_not_called()
            self.assertEqual(sorted(packet, key=lambda r: r['unit_id']), sorted(full, key=lambda r: r['unit_id']))
            self.assertEqual(audit['status'], 'BASELINE_UNITS_REORDERED')

    def test_rag_char_limit_and_five_units_never_truncate_sources(self):
        base = [row('base', role='CODING_GUIDELINE')]
        candidates = [row(str(i), '복통 통증 문진 조건 예외 ' * 30) for i in range(9)]
        with patch('nova_agent.experiments.reference_packet', return_value=candidates):
            packet, _ = clinical_packet(None, '복통 통증', base, 2500)
        self.assertLessEqual(len(packet), 5)
        self.assertGreater(len(packet), 1)
        self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False)), 2500)
        for item in packet:
            self.assertIn(item, base + candidates)
        self.assertIn(base[0], packet)

    def test_existing_clinical_unit_skips_costly_second_search(self):
        base = [row('coding', role='CODING_GUIDELINE'), row('clinical')]
        with patch('nova_agent.experiments.reference_packet') as search:
            packet, audit = clinical_packet(None, '복통 통증', base, 12000)
            search.assert_not_called()
        self.assertEqual(packet, list(reversed(base)))
        self.assertEqual(audit['searches'], 0)
        self.assertEqual(audit['search_skipped'], 'EXISTING_TOPICAL_CLINICAL_UNIT')

    def test_real_guidelines_source_and_exception_preserved_and_hash_error_falls_back(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); (root / 'SYNTH').mkdir()
            with (root / 'catalog.csv').open('w', encoding='utf-8', newline='') as f:
                w = csv.writer(f); w.writerow(['파일명','제목','발행기관','연도','언어','문서 유형','형식','라이선스','출처 URL'])
                w.writerow(['SYNTH/a.md','Fever assessment','Synthetic','2026','영어','진료지침','Markdown','CC0','https://example.invalid/a'])
            source = root / 'SYNTH/a.md'
            source.write_text('---\ntitle: "Fever assessment"\norganization: "Synthetic"\nyear: 2026\nlanguage: en\nsource_url: "https://example.invalid/a"\nlicense: CC0\n---\n# Fever\n## Assessment\nFever pain assessment examination.\n### Exception\nDo not omit this condition or exception.\n', encoding='utf-8')
            db = root / 'index.sqlite'; build(root, db)
            guide = GuidelinesIndex(db, root)
            try:
                packet, audit = clinical_packet(CombinedIndex(guidelines=guide), 'fever pain', [], 12000)
                self.assertTrue(packet)
                self.assertIn('Do not omit this condition or exception.', packet[0]['text'])
                self.assertTrue(packet[0]['source_sha256'])
                source.write_text('modified after indexing', encoding='utf-8')
                base = [row('safe-base')]
                self.assertEqual(clinical_packet(CombinedIndex(guidelines=guide), 'fever pain', base, 12000)[0], base)
            finally:
                guide.close()

    def test_last_query_cache_is_local_and_record_stays_baseline(self):
        for strategy in ('V1', 'V4'):
            r = loop.Run(None, loop.State(NoResults(), strategy=strategy), {})
            r.facts = [fact('F0', 'opening', '복통 통증')]
            with patch('nova_agent.loop.clinical_packet', return_value=([row('extra')], {'status': 'SYNTHETIC', 'added_ids': ['extra'], 'searches': 1})) as select:
                first, _ = r.context(10); r.context(9)
                record, _ = r.context(9, for_record=True)
                self.assertEqual(select.call_count, 1)
                self.assertEqual(json.loads(record)['reference_evidence'], [])
                self.assertEqual(json.loads(first)['reference_evidence'][0]['unit_id'], 'extra')
            self.assertIsNone(loop.Run(None, loop.State(NoResults(), strategy=strategy), {}).clinical_cache)

    def test_integrated_mode_cannot_bypass_test_length_or_done_contract(self):
        c = MockClient([{'action': 'TEST', 'content': '검사'}, say('가' * 31),
                        say('검사 필요성을 설명드릴게요', 'EXPLAIN'), {'action': 'DONE'}, plan()])
        s = loop.State(NoResults(), loop.Config(retry_delay=0), strategy='V4')
        loop.consult(c, s)
        self.assertEqual(s.report['invalid_model_outputs'], 2)
        self.assertFalse(any(call['action'] == 'TEST' for call in c.calls))
        self.assertEqual(s.report['termination_reason'], 'DOCTOR_DONE')
        self.assertEqual(s.report['action_record_headrooms'][0]['reserved_calls'], 3)
