# 임상 평가 근거 하네스 2단계 — 2026-10-21

진료 코드 변경 없이 기존 하네스를 확장했다. 구현 부모는 `codex/nova-development-harness`의 `da0126c82cb752991c52f11191d830681d8bccba`, 진료 baseline은 v3.5 `81714d340207a8e5ca9886dd2129cbd6b9cc61f2`다. app/STEP/RECORD/모델/RAG/SDK/예산은 변경하지 않았다. 새 진료·모델 API·웹사이트 평가·제출·Docker/GCP·main 병합은 실행하지 않았다.

## 사례와 근거

- 10개 검토 사례: 과거 개발 로그 기반 5개, 새 합성 4개, 기존 example 1개. 주호소 문진, 미시행 진찰, 부분 답변 확대, 반복 질문, 직접 질문 미응답, P/SAY 차이, 위험 확인 지연, 반복 설명을 다룬다. 유효한 재확인 대조 사례도 포함했다.
- 공개 C01/C10/C03의 case.json·참고 기록 6개, v3.2/v3.3 개발 로그·버전 메타데이터 12개를 **원위치에서 읽고 해시·JSON Pointer만 연결**했다. 원문·원장·후보를 복제하지 않았다. 과거 로그는 v3.5/v3.8 결과가 아니며 웹사이트 세부 로그는 없다.
- 사례별 조건·기대 행동 범위·금지 오류·사람 판단·근거 ID는 [카탈로그](../../harness/cases/clinical_review.json), 출처별 설명과 검토 명령은 [평가 문서](../../docs/EVALUATION.md)에 있다. 공개 진찰표 전체나 모범 기록을 필수 정답으로 사용하지 않는다.

## 자동 검사와 검토 경계

| 자동 확인 | 사람 검토 / 미평가 |
|---|---|
| 해시·원본 버전·포인터·관찰 ID 정합성 | 자료가 없으면 NOT_EVALUATED, 자동 임상 점수 없음 |
| SDK OK + turn/행동/응답을 연결한 ASK/EXAM/EXPLAIN ID | 어떤 문진·진찰이 필요했는지, 적정 시점·충분성 |
| 질문/답변 원문의 기록 포함, P와 실제 설명의 문자 일치 | 요약·동의어·부분 답변 확대·P 전체의 실제 전달 여부 |
| NFC 동일 문장 반복 표시 | 유효한 재확인인지 불필요한 반복인지 |
| 마지막 보존 Doctor 관찰의 성공 행동 근거, 평가자 키·위조 관찰 거부 | 모든 과거/미래 프롬프트 또는 의미상 유출 보장 아님 |
| 근거·검토자·이유 없는 사람 판정 입력 거부 | 검토자 자격·판정의 진위, 환자 이해, 실제 임상 품질 |

근거 검증 PASS는 임상 PASS가 아니다. 10개 임상 사례는 모두 REVIEW이며 사람 판정을 대신 입력하지 않았다. P의 일부분과 SAY가 같아도 전체 설명 전달로 인정하지 않는다. 추적 정보가 없으면 미시행으로 확정하지 않는다. 서버 completed·내부 종료 이유·기록 결과는 따로 보존한다.

## 검증

- 하네스/평가자 분리/신규 검토 도구 초기 21개 PASS(5+5+11).
- 원본 대조에서 EXAM의 `result`를 SAY의 `content`와 혼동한 새 어댑터 오류를 발견했다. 필드 처리를 고치고 미시행 진찰 혼입 방지 회귀를 추가했다. 영향받은 신규 묶음만 12개 재실행하여 PASS. 전체 테스트를 반복하지 않았다.
- 최종 원본/합성 해시 20개 PASS, 10개 사례 포인터 해석 성공. 보존된 6개 마지막 Doctor 관찰은 성공 이벤트와 대조해 PASS. 이는 전 턴 입력 감사나 임상 품질 인증이 아니다.
- 원래 v3.8 candidate: 행동·관찰·전달 30개 + 기록·예산 14개 PASS. scope REVIEW, 보호 AST 및 실행 전후 app 보존 PASS. 임상 품질 NOT_EVALUATED.
- 상세 검사 ID·자료 해시·미평가 구분은 [validation.json](validation.json). 최초 어댑터 오류 출력과 재검증 출력은 Git 제외 `reports/harness_runs/phase2_*`에 보존했다.

## v3.8 보호

원래 checkout은 `codex/nova-v3-8-clinical-coverage`, HEAD `81714d340207a8e5ca9886dd2129cbd6b9cc61f2`다. `loop.py`, `prompts.py` 수정 및 미추적 `coverage.py`는 그대로 남아 있다. 세 파일의 작업 전후 SHA-256 일치를 확인했다(전체 해시는 validation.json).

변경 의도는 관찰 ID별 확보 정보·실제 EXAM/EXPLAIN 탐색과 선택적 다음 행동 메모다. 필수 완료 상태나 DONE 차단을 추가하는 구조는 아니며 RECORD 입력은 별도로 보존하려는 미완성 작업이다. 이번에는 읽기·오프라인 검사만 수행했고 파일 수정·삭제·커밋·덮어쓰기나 개발 재개는 하지 않았다.

## 변경 파일과 다음 사용

| 파일 | 변경 |
|---|---|
| scripts/dev_harness.py | 기존 실행기에 review 명령·관련 테스트 묶음 연결 |
| scripts/clinical_review.py | 읽기 전용 근거 연결·행동/기록 대조·사람 판정 검증 |
| harness/cases/clinical_review.json | 원본 경로/해시 20개 및 검토 사례 10개 |
| harness/cases/clinical_synthetic.json | 부족한 4개 상황의 합성 자료 |
| tests/test_clinical_review.py | 새 도구의 확인된 공백 회귀 12개 |
| docs/EVALUATION.md, docs/HARNESS.md | 범위·상태·기술적 한계·실행 명령 |
| reports/clinical_review_20261021/{REPORT.md,validation.json} | 원문 없는 검증 근거 |

하네스 디렉터리에서 Python 3.12로 실행한다. 이 PC의 실행 파일은 `../nova_rag_dev_20261015/doctor_agent_v2/validation/python312/python.exe`다.

```powershell
python -X utf8 -B -I scripts/dev_harness.py review
python -X utf8 -B -I scripts/dev_harness.py review --show-evidence
python -X utf8 -B -I scripts/dev_harness.py check --group clinical_review --group evaluator_separation --group harness
# 추후 별도 v3.8 구현 지시를 받은 뒤, 변경 관련 묶음만 선택
python -X utf8 -B -I scripts/dev_harness.py check --repo ../nova-medical-agent --candidate --group action_observation_delivery --group final_record_budget
```

`review`는 현재 보존 자료를 대조하며 새 후보를 실행하지 않는다. 이번 작업 종료 후 v3.8 구현을 자동 재개하지 않는다.
