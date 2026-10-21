# Evaluation evidence, not a hidden scorecard

목표는 정보수집과 의사소통의 실제 행동 근거를 남기는 것이다. 비공개 채점 항목·가중치·만점 답안을 추정하지 않는다. 턴 수나 설명 횟수의 증감만으로 좋고 나쁨을 판단하지 않는다.

## 사례 형식

[합성 예시](../harness/cases/example.json)는 실행 대본이 아닌 검토 형식이다. `case-check`는 JSON 구조와 근거 연결만 검사하며 Doctor를 호출하지 않는다.

| 필드 | 의미 |
|---|---|
| schema_version, case_id, provenance | 형식 버전, 식별자, 실제 출처·버전·수집일·원본 해시. 예시는 수작성 합성 자료로 표시 |
| doctor_input | opening/vital_signs/observations만 허용. 실제 응답으로 확보한 정보만 추가; 질문 자체를 환자 사실로 승격하지 않음 |
| evaluator_only | 환자 대본·진찰 결과표·참고 기록. 평가자 자료이며 Doctor나 RAG에 전달하지 않음 |
| trace | 행동 ID, SAY/EXAM 등, intent, 전송 문장, 실제 응답, 성공 확인. 실패·거절·DONE·DIAGNOSE도 구분해 기록 가능 |
| final_record | 최종 기록 원문. P의 계획, 실제 SAY, 환자 이해를 각각 검토 |
| criteria | domain, applicability, review_question, status, evidence, reason. trace ID 또는 존재하는 record 필드를 근거로 지정 |

정보수집 누락, 필요한 진찰, 부분 답변 확대, 반복 질문, 직접 질문 무응답, P에만 있는 설명, 위험 확인, 무의미한 추가 턴을 각각 **해당 증례에서 적용 가능한지부터** 검토한다. 모든 환자에게 동일 목록을 수행시키는 규칙이 아니다. 단순 “네”나 설명 태그로 이해·안전 안내 완료를 인정하지 않는다.

| 상태 | 해석 |
|---|---|
| PASS | 명시된 좁은 검사 또는 사람 검토 항목에 긍정 근거가 있음. 다른 임상 영역까지 통과했다는 뜻은 아님 |
| FAIL | 실제 실패를 재현했거나 근거를 통해 확인. 근거 ID·코드 위치·실패 종류를 남김 |
| REVIEW | 적용 여부·임상 의미·허용 범위가 불확실해 사람이 판단해야 함 |
| NOT_EVALUATED | 필요한 모델 응답·세부 로그·평가 근거가 없어 판단하지 않음 |

PASS/FAIL/REVIEW에는 근거와 이유가 필요하다. 형식 검사 통과는 작성자의 판정이 참임을 보장하지 않는다. 모델 없이 검증할 수 있는 것은 실행 형식·보존·분리·예산 경계다. 다음 질문/진찰의 적절성, 설명 충분성, 위험 신호 인식, 안전 점수는 별도 실제 근거가 필요하다.

실제 자료는 Git 밖에서 원본을 읽고 해시·포인터만 기록한다. 2단계에서는 공개 샘플 3건의 patient_script/exam_results/model_record와 과거 개발 로그 6건을 로컬 참조로 연결했다. 모범 기록은 만점 기준이나 필수 수행 목록이 아니다. 원본 로그·원장은 수정·초기화·복제하지 않는다. 합성 예시와 기존 개발 API 로그, 웹사이트 사용자 보고, 공식 평가를 혼합하지 않는다.

실험 결과에는 baseline/candidate 커밋, 실제 파일 해시, 변경 범위, 실행 명령·환경, 모델/예산 유지 여부, 사례 출처, 자동 검사 결과, 미평가 항목을 남긴다. 서버 completed, 내부 DOCTOR_DONE, 기록 형식 유효, fallback, 임상 적절성은 서로 다른 판정이다.

## 2단계: 근거 대조와 사람 검토

`harness/cases/clinical_review.json`(schema_version 2)은 위의 단일 사례 v1을 대체하지 않는 **검토 카탈로그**다. 원본별 로컬 상대 경로·SHA-256·자료 종류·생성 버전을 고정하고 JSON Pointer와 관찰 ID로 원문을 참조한다. 개발 로그의 버전은 별도 해시 고정된 실행 메타데이터와 대조한다. 현재 Git HEAD로 과거 실행 버전을 추정하지 않는다. `clinical_synthetic.json`은 부족한 조건을 보충하는 수작성 자료이며 Doctor가 생성한 응답이 아니다.

| 사례 | 출처와 핵심 근거 | 검토 쟁점 |
|---|---|---|
| complaint-history-gap | 새 합성 history_gap | 주호소 문진 없이 종료 |
| unperformed-exam | C01 v3.2 events, 공개 C01 진찰표·참고 O | 성공한 EXAM 없음과 필요한 진찰 미실시는 별도 판단 |
| partial-answer-overclaim | C03 v3.3 F8, S.ros, A.differential | 피로만 답했는데 추위·변비까지 확대했는지 |
| already-answered-repeat | 새 합성 repeated_answer | 명확한 답 이후 같은 질문; 필요성은 사람 검토 |
| patient-question-unanswered | 새 합성 direct_question | 환자 직접 질문에 대응하거나 확인 이유를 설명했는지 |
| record-plan-vs-spoken | C03 v3.3 F20~F22, P.follow_up, 참고 P | 추적·악화 안내가 P에만 있는지 실제 SAY 전체와 대조 |
| risk-assessment-delay | 새 합성 risk_delay | 위험을 시사하는 발화 이후 무관한 문진 우선 |
| similar-explanation-repeat | C03 v3.3 F20~F22 | 각 설명이 추가 정보를 주었는지, 이해 반응에 맞았는지 |
| needed-clarification-control | C10 v3.3 F17~F18, 공개 C10 자료 | 부분 답변 뒤 유효한 재확인을 반복 오류로 오판하지 않기 |
| existing-example-partial-and-understanding | 기존 example.json T1~T2 | 부분 답변·이해 곤란; 전체 trace가 아님 |

각 사례에는 `applicability`, `expected_range`, `forbidden_errors`, `human_review`가 있다. 질문 문구·개수·설명 횟수를 정답으로 고정하지 않는다. 공개 자료는 적용 조건을 검토하는 참고이며 당시 환자가 실제 답한 사실은 실행 로그에서만 가져온다. 공개 샘플 C01/C10/C03 각각의 case.json·model_record.json 6개와 v3.2/v3.3 로그·버전 메타데이터 12개를 원위치에서 읽는다. 웹사이트 세부 로그는 없으므로 NOT_EVALUATED다.

```powershell
# 원본 복제 없이 해시, 실제 행동, 기록 대조. 새 출력 폴더에 원문 없는 보고서 생성
python -X utf8 -B -I scripts/dev_harness.py review
# 검토자만 원문 확인: 콘솔에 참조 위치의 값을 표시하며 보고서에는 원문을 저장하지 않음
python -X utf8 -B -I scripts/dev_harness.py review --show-evidence
# 관련 테스트만 실행 (임상 모델 호출 없음)
python -X utf8 -B -I scripts/dev_harness.py check --group clinical_review --group evaluator_separation --group harness
```

`--workspace`는 보존 자료가 있는 상위 디렉터리다. 자료가 없으면 NOT_EVALUATED, 해시 불일치나 잘못된 포인터는 FAIL이며 임의의 다른 버전으로 대체하지 않는다. 출력은 기존 `reports/harness_runs/` 아래 새 폴더다. 원문 콘솔 출력을 파일로 리다이렉트해 원본을 복제하지 않는다. 기준 예시·합성 자료를 수정하면 카탈로그의 해당 해시도 검토 후 갱신해야 한다.

### 자동으로 확인하는 범위

- SDK `OK`와 turn·질문·응답 일치로 관찰 ID를 연결한다. SAY의 `content`와 EXAM의 `result`를 구분한다. 연결되지 않은 SAY의 ASK/EXPLAIN 의도는 추정하지 않는다.
- 문진·진찰·설명 실행 ID, 질문/응답 원문이 동일 기록 필드에 포함되는지, P에 포함된 실제 EXPLAIN 문장을 나란히 제공한다. **원문 일치 PASS는 임상 적절성 PASS가 아니다.** 불일치는 요약·동의어일 수 있어 REVIEW다.
- P에 실제 설명 한 문장이 포함되어도 P 전체가 전달되었다고 판정하지 않는다. 성공 응답과 환자 이해는 별도다. 단순 “네”를 이해 증거로 자동 인정하지 않는다.
- 성공 행동 수를 기존 report와 대조해 해당 성공 이벤트 범위의 완전성을 표시한다. 거절·재생성된 모든 모델 행동이나 모든 턴의 Doctor 입력을 복원하지 않는다. trace가 없으면 미수행을 단정하지 않는다.
- NFC 동일 문장 반복을 표시하되 유효한 재확인인지 REVIEW로 남긴다. 유사 의미·부분 답변의 임상 해석·위험 확인 시점은 자동 판정하지 않는다.
- 마지막 보존 Doctor 컨텍스트의 관찰을 성공 이벤트에 연결된 허용 관찰과 대조한다. 평가자 키의 중첩 유입·위조 ID·미실시 진찰 결과를 거부하는 회귀가 있다. 이것은 **보존된 컨텍스트 및 하네스 투영 경로의 검사**이며 모든 실제 프롬프트·의미상 유출을 보장하는 보안 장벽은 아니다. 초기 발화·활력징후의 원출처 진위 역시 별도 검토 대상이다.

### 사람 검토 기록

기본 사례 상태는 근거가 모두 있으면 REVIEW, 부족하면 NOT_EVALUATED다. 자동 임상 점수는 없다. 검토자는 원문을 확인한 뒤 별도 로컬 JSON 목록을 `--decisions 경로`로 읽힐 수 있다. 각 항목은 `case_id`, `reviewer`, `reviewed_at`, `status`, `reason`, `evidence: [{source, pointer}]`를 가진다. evidence는 해당 사례의 해시·포인터 검사를 통과한 근거만 허용한다. 예를 들어 원문 보존과 추론의 적절성은 다른 판단으로 이유에 명시한다. 검토자 신원·전문성·판단의 진위는 이 스크립트가 인증하지 않는다.

자동 검사 전체 상태는 무결성/분리 오류가 있으면 FAIL, 그 외 REVIEW다. 개별 사람 판정은 `human_decision`에 별도 보존되며 자동 인증으로 승격하지 않는다. 보고서에 임상 점수와 웹사이트 세부 평가는 계속 NOT_EVALUATED로 표시한다. 향후 새 trace는 기존 원본을 덮어쓰지 말고 새 버전·출처·해시와 근거 포인터를 카탈로그에 추가한다. 이 단계의 사례를 통과해도 v3.8 정보수집·의사소통 개선이나 안전 점수를 입증하지 않는다.
