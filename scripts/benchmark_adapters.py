"""Evaluation-only adapters. Raw benchmark records never enter app/ or RAG.

English is preserved; no translation/model-generated cases. IDs retain splits.
"""
import ast
import csv
from dataclasses import dataclass
import io
import json
import random
import shutil
import tempfile
import zipfile

PREFIX = 'nova-benchmarks-2026/'
SPLITS = {'train': 1025602, 'validate': 132448, 'test': 134529}
ACI = {'train': 'train.csv', 'valid': 'valid.csv',
       'test1': 'clinicalnlp_taskB_test1.csv', 'test2': 'clinicalnlp_taskC_test2.csv',
       'test3': 'clef_taskC_test3.csv'}


@dataclass
class EvaluationCase:
    case_id: str
    dataset: str
    split: str
    initial: dict
    simulator_private: dict
    evaluator_private: dict

    def doctor_input(self):
        # Explicit allowlist, not serialized dataclass/asdict.
        return {'case_id': self.case_id, 'task': self.dataset,
                'observations': self.initial, 'language': 'en', 'translation': None}

    def evaluator_input(self):
        return dict(self.evaluator_private)


def agentclinic(row, number):
    x = row['OSCE_Examination']; actor=x['Patient_Actor']
    symptoms=actor.get('Symptoms', {})
    opening = symptoms.get('Primary_Symptom', '') if isinstance(symptoms, dict) else ''
    if not opening:
        # No fallback to full history or Objective_for_Doctor (can reveal diagnosis).
        opening = 'Chief complaint not supplied separately; ask the patient.'
    physical=x.get('Physical_Examination_Findings', {})
    return EvaluationCase(f'agentclinic:extended:{number}', 'AgentClinic-MedQA', 'extended',
        {'opening': opening, 'demographics': actor.get('Demographics', ''),
         'vital_signs': physical.get('Vital_Signs', {})},
        {'patient_script': actor, 'exam_results': physical},
        {'diagnosis': x['Correct_Diagnosis'], 'withheld_TEST_results': x.get('Test_Results', {}),
         'task_difference': 'Preliminary mode withholds TEST; original AgentClinic permits tests.'})


def ddx_answer(evidences, code, dictionary):
    spec=dictionary[code]; values=[]
    for item in evidences:
        name, sep, value = item.partition('_@_')
        if name != code:
            continue
        if not sep:
            values.append(True)
        else:
            values.append(spec.get('value_meaning', {}).get(value, {}).get('en', value))
    if values:
        return values
    default=spec.get('default_value')
    return [spec.get('value_meaning', {}).get(str(default), {}).get('en', default)]


def ddxplus(row, number, split, dictionary):
    evidence=ast.literal_eval(row['EVIDENCES'])
    code=row['INITIAL_EVIDENCE'].split('_@_')[0]
    initial={'age': row['AGE'], 'sex': row['SEX'], 'initial_evidence_code': code,
             'initial_question': dictionary[code]['question_en'],
             'initial_response': ddx_answer(evidence, code, dictionary)}
    return EvaluationCase(f'ddxplus:{split}:{number}', 'DDXPlus', split, initial,
                          {'evidences': evidence},
                          {'diagnosis': row['PATHOLOGY'], 'differential': row['DIFFERENTIAL_DIAGNOSIS']})


def ask_ddx(case, code, dictionary):
    if case.dataset != 'DDXPlus' or code not in dictionary:
        raise ValueError('UNKNOWN_DDX_QUESTION')
    spec=dictionary[code]
    return {'question_code': code, 'question_group': spec.get('code_question', code),
            'question': spec['question_en'],
            'answer': ddx_answer(case.simulator_private['evidences'], code, dictionary)}


def aci(row, split):
    return EvaluationCase('aci:' + split + ':' + row['encounter_id'], 'ACI-Bench', split,
                          {'observed_dialogue': row['dialogue'], 'task': 'note_generation'}, {},
                          {'reference_note': row['note'], 'diagnosis_accuracy': None,
                           'task_difference': 'Recorded dialogue; not an interactive diagnosis task. Speaker labels may be wrong.'})


def select_cases(archive, seed=20261015):
    """Five per dataset; CSV streams never become a full patient dataframe."""
    rng=random.Random(seed); selected=[]; counts={}
    with zipfile.ZipFile(archive) as z:
        selected_agent=set(rng.sample(range(215), 5))
        with z.open(PREFIX+'AgentClinic-MedQA/agentclinic_medqa_extended.jsonl') as f:
            count=0
            for i,line in enumerate(f):
                count+=1
                if i in selected_agent:
                    selected.append(agentclinic(json.loads(line), i))
            counts['AgentClinic-MedQA']=count
        dictionary=json.loads(z.read(PREFIX+'DDXPlus/release_evidences.json'))
        for split, size in SPLITS.items():
            take=set(rng.sample(range(size), 1 if split=='validate' else 2))
            # Outer ZIP embeds a ZIP. Spool the compressed member to disk, not RAM.
            with tempfile.TemporaryFile() as spool:
                with z.open(PREFIX+f'DDXPlus/release_{split}_patients.zip') as source:
                    shutil.copyfileobj(source,spool)
                spool.seek(0)
                with zipfile.ZipFile(spool) as inner:
                    names=[n for n in inner.namelist() if not n.endswith('/')]
                    if len(names)!=1: raise ValueError('DDX_CSV_MEMBER_COUNT')
                    with inner.open(names[0]) as f:
                        rows=csv.DictReader(io.TextIOWrapper(f,encoding='utf-8-sig',newline=''))
                        count=0
                        for i,row in enumerate(rows):
                            count+=1
                            if i in take: selected.append(ddxplus(row,i,split,dictionary))
                        counts['DDXPlus:'+split]=count
                        if count!=size:raise ValueError('DDX_SPLIT_COUNT_MISMATCH')
        for split, name in ACI.items():
            n=67 if split=='train' else 20 if split=='valid' else 40
            pick=rng.randrange(n)
            with z.open(PREFIX+'ACI-Bench/aci-bench-corpus/challenge_data/'+name) as f:
                count=0
                for i,row in enumerate(csv.DictReader(io.TextIOWrapper(f,encoding='utf-8-sig',newline=''))):
                    count+=1
                    if i==pick:selected.append(aci(row,split))
                counts['ACI-Bench:'+split]=count
    return selected, dictionary, counts
