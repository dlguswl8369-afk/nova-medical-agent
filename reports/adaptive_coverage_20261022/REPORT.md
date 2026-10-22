# H5/H6 독립 임상 실행 실험 · 2026-10-22

기준 v3.5 `81714d340207a8e5ca9886dd2129cbd6b9cc61f2`에서 새 작업 디렉터리·브랜치로 직접 분기했다. 기존 H1–H4의 제한된 호출·예산 보호·패키징 도구를 선택적으로 재사용했고 하네스를 다시 만들거나 수정하지 않았다. **두 후보의 실제 임상 성능은 NOT_EVALUATED**다. 정보수집·의사소통 점수 개선이나 안전 점수 유지를 보장하지 않는다.

| 후보 | 실제 실행 구조 | 보조 Doctor 호출 최대 | 주요 비용·임상 위험 |
|---|---|---:|---|
| H5 Adaptive Clinical Workflow | 첫 성공 행동 이후 최신 답변을 읽은 ACTION이 긴급 표시를 하지 않으면 자동 계획 호출. readiness 불필요. 계획은 다음 행동을 제안할 수 있으나, PLAN의 DONE은 진행 중인 유효 행동을 종료시키지 못함. 새 답변에 따라 같은 ACTION의 plan_update로 수정 가능. 새 관찰이 생긴 뒤 첫 DONE에서 계획 갱신·미확인 사항 검토를 한 번 더 수행 | PLAN 1 + REFRESH 1 = **2회** | 계획 고착, 계획 이후 정보의 과해석, 계획 호출 지연. 최초 계획의 DONE을 무시하면서 기존 행동 한 번이 불필요하게 수행될 가능성 |
| H6 Coverage-First | 같은 ACTION 호출에서 필요한 질문·진찰·설명을 중요도 순으로 최대 3개 제안. 실제 관찰 ID와 판단 목적이 있고 기존 행동 계약을 통과한 첫 대안 하나만 실행. 나머지는 폐기하고 다음 환자 반응 후 새로 선택. 첫 DONE에서 실제 이행·중요 누락을 한 번 독립 검토 | AUDIT **1회** | 대안 작성의 출력 비용·형식 부담, 잘못된 우선순위·불필요한 진찰/설명. 원문 ID 존재가 임상적 적절성을 보장하지 않음 |

두 ZIP은 전략이 고정되어 추가 설정 없이 실행된다. H5에는 H6 대안 선택·독립 AUDIT를 넣지 않았고, H6에는 지속 계획·PLAN·REFRESH가 없다. 둘 다 기존 단일 행동을 허용한다. H6의 최대 3개는 **한 호출의 미실시 대안 수**이지 필수 질문·진찰·설명 횟수가 아니다. 고정 문진표·진단·설명 순서가 없고, 충분하면 DONE을 허용한다.

## 변경과 유지

- `app/nova_agent/loop.py`: PLAN/REFRESH/AUDIT를 기존 Doctor 원장에 연결. H5의 자동 호출·조기 DONE 방지·관찰 이후 갱신, H6의 한 행동 선택·첫 DONE 검토. 거부된 EXAM의 문구와 이유는 실패 이력으로만 전달한다.
- `app/nova_agent/workflow_strategy.py`: 환자별 계획·갱신·종료 검토 지침, H6의 현재 응답에 한정된 대안 선택. 임상 의미를 정규식으로 판정하지 않는다. 실행 STEP에서 “검사 계획은 최종 P에만” 문구 충돌을 해소했다.
- `app/nova_agent/experiment_config.py`: 저장소 기본값 BASELINE, ZIP별 H5/H6 고정.
- `scripts/check_workflow.py`, `tests/test_workflow_policy.py`: 기존 하네스와 H1–H4의 좁은 정책을 재사용. 보호 심볼 중 `Run.doctor`의 명시된 보조 호출 변경만 허용하고, 추가 목적 REFRESH와 medium/3072 설정을 고정 검사한다.
- `tests/test_workflow.py`, `scripts/package_workflow.py`, `scripts/review_workflow.py`: 관련 실행 회귀, 실제 ZIP 진입점 mock, 기존 사례의 읽기 전용 관찰 대조. 이 보고서와 `RESULTS.json`은 결과·출처만 저장한다.

v3.5의 `prompts.py` 파일 및 RECORD 문자열, SDK, RAG 자료·선택·검색 예산, 실제 관찰 ID와 원문 S/O 조립, 설명 전송 성공과 이해 구분, 모델, Config, 기록 예산 보호는 유지했다. 새 계획·갱신 메모·미선택 대안·실패한 EXAM은 관찰이나 수행 기록으로 저장하지 않는다. 계획은 RAG 질의와 RECORD 입력에도 들어가지 않는다. STEP은 실행 시 전략별로 구성되므로 **실행 프롬프트가 baseline과 같다는 뜻은 아니다**.

## 시간·호출·토큰

모든 호출은 `openai/gpt-6-luna`, `medium`이다. ACTION 2048, RECORD 4096, PLAN/REFRESH/AUDIT 3072의 출력 상한을 사용한다. 보조 출력 예약 최대는 H5 **6144**, H6 **3072**이며 추론 토큰도 포함한다. 보조 호출은 각각 HTTP 최대 한 번, 타임아웃 120초이고 자동 재시도하지 않는다.

기존 **30턴·Doctor 80회·입력 500,000/출력 100,000·최종 기록 시간 여유 300초**를 유지했다. 보조 호출은 남은 시간 480초 이하·행동 여유 부족·최종 기록 예산 예약 불가이면 생략한다. 세 번의 최종 RECORD 생성 여유를 기존 방식으로 예약한다. 한 번의 계획·검토가 후속 ACTION과 행동을 늘릴 수 있으므로 보조 호출 상한이 총 추가 호출·턴 상한은 아니다. 실제 비용·지연은 측정하지 않았다.

H5의 초기 계획은 `planning_ready`가 없어도 호출되지만 **시간·예산·실행 오류·긴급 우선 조건보다 강제하지 않는다**. 현재 답변의 긴급성은 ACTION 모델의 `urgent:true`에 의존하므로 위험 신호를 임상적으로 놓치지 않는다는 보장이 아니다. 계획 응답이 잘못되거나 실패하면 기존 행동을 유지하며, 새 관찰 이후 갱신에서 회복할 수 있다. H6의 대안이 없으면 유효한 단일 행동을 사용하고, 검토가 실패하면 원래 DONE을 허용한다. 이는 충분성이 임상적으로 검증됐다는 뜻이 아니다.

## 오프라인 검증

고정 하네스 `93abcdcdef146a0ade5a55c0ae5b4b70a7a0bb2c`의 네트워크·하위 프로세스·출력 외 쓰기 차단을 재사용했다. **서로 다른 테스트 76개 PASS**: 기존 관련 회귀 55개, 새 전략 14개, 정책 7개. 최초 75개 통과/1개 실패였고, 세션 누출 검사에서 공통 프롬프트 단어를 개별 메모로 오인한 테스트를 고유 표식으로 수정해 해당 1개만 재실행했다. 실행 코드는 두 검사 사이에 바뀌지 않았다. 최초 결과도 보존하며 통합 결과는 두 검사 파일의 해시와 근거를 연결한다.

자동 확인: readiness 없는 계획 활성화, 진행 중 PLAN→DONE 방지, 현재 긴급 행동 우선, 새 관찰 이후 갱신 한 번, 충분한 DONE 허용, 한 후보만 실행·나머지 폐기, 중복·부적합 대안 처리, EXAM_NOT_SPECIFIC/NOT_RECOGNIZED 복구, 부분 답변 원문, 실제 설명과 P 구분, NFC 30자·TEST 금지, 예산·타임아웃·기록 예약, 세션 간 상태 독립, 정상/fallback DIAGNOSE 경로. 서버 만료·네트워크 장애에서도 DIAGNOSE 접수까지 보장하지 않는다.

기존 공개/합성 자료·v3.2/v3.3 개발 로그의 출처 해시 20개, 10개 검토 사례 × BASELINE/H5/H6의 **30개 컨텍스트 대조 PASS**. 해당 자료에서 관찰·RECORD 입력 보존, 선택 누락 0개. 빈 검색 인덱스 조건의 구조 대조이며 실제 RAG는 파일 동일성으로 보호했다. 계획 없는 ACTION 입력 증가는 H5 +822, H6 +1098 UTF-8 바이트다. 실제 토큰 수가 아니며 H5의 최대 1600자 계획이 추가되면 입력은 더 늘어난다.

10개 사례의 문진·진찰 필요성, 부분 답변에 대한 추론 범위, 직접 질문 응답, 실제 설명 의미, 위험 확인 시점, 반복 필요성, 안전한 DONE은 **REVIEW**다. 과거 trace를 H5/H6 실행 결과로 취급하지 않았다. 대본·진찰표·모범 기록은 평가자 영역에 두며 후보 ZIP에 포함하지 않는다. 긴 진료에서 기존 fact_chars 한도가 과거 관찰을 가리는 위험도 그대로 남는다. mock은 지정한 행동을 실행하므로 임상적 선택 능력·설명 품질·점수는 **NOT_EVALUATED**다.

## 재현과 보존

Python 3.12, 저장소 루트에서 새 출력 경로를 지정한다. 기존 결과는 덮어쓰지 않는다.

```powershell
$py = '../nova_rag_dev_20261015/doctor_agent_v2/validation/python312/python.exe'
& $py -X utf8 -B -I scripts/check_workflow.py --output ../nova_adaptive_coverage_20261022/checks-new
& $py -X utf8 -B -I scripts/review_workflow.py --output ../nova_adaptive_coverage_20261022/review-new
& $py -X utf8 -B -I scripts/package_workflow.py --output ../nova_adaptive_coverage_20261022/zips-new --validation ../nova_adaptive_coverage_20261022/checks-new/validation.json
```

기존 작업 디렉터리 HEAD: v3.8 `3b348d1d86621c880c2aca6fb1d9d3f89a3adb07`, V1–V4 `50409240107b152705e3e278df8466a3e360ea28`, H1–H4 `91b48ddd621972b71fedbb433dccb2b169bb1d3c`, 하네스 `93abcdcdef146a0ade5a55c0ae5b4b70a7a0bb2c`. 모두 미커밋 변경 없이 시작했고 이번 작업으로 변경하지 않았다. 기존 후보·로그·원장을 덮어쓰거나 초기화·복제하지 않았다. 실제 API·새 진료·웹사이트 검증·제출·main 병합·Docker/GCP는 실행하지 않았다.

새 브랜치 `codex/nova-adaptive-coverage-experiments`. 이 보고서를 포함하는 커밋에 코드·테스트·스크립트·결과만 추가한다. ZIP·인덱스·원문·비밀정보는 새로 Git에 넣지 않는다.

## 고정 ZIP 및 진입점 근거

| 후보 ZIP | 바이트 | SHA-256 | 진입점 mock / 보조 호출 |
|---|---:|---|---|
| [nova_doctor_bm25_candidate_H5_adaptive_clinical_workflow_20261022.zip](<C:/Users/hjlee/OneDrive/문서/ChatGPT/의료 ai agent/nova_adaptive_coverage_20261022/deliverables/nova_doctor_bm25_candidate_H5_adaptive_clinical_workflow_20261022.zip>) | 44,994,081 | `27f5cd73ee57d7c4525782eafe90c69a18ec7941ffb934fa2dd6eecfdc957366` | PASS / 2회 |
| [nova_doctor_bm25_candidate_H6_coverage_first_20261022.zip](<C:/Users/hjlee/OneDrive/문서/ChatGPT/의료 ai agent/nova_adaptive_coverage_20261022/deliverables/nova_doctor_bm25_candidate_H6_coverage_first_20261022.zip>) | 44,994,082 | `05e8e07f7d306a8d59d4649f36037f78e1c3a7f070d621ff083cad4bc91cb093` | PASS / 1회 |

두 ZIP 모두 45MB 미만, 26개 파일, 루트 `run.py`·`requirements.txt`, CRC·구문·크기·압축 해제 후 해시 검사 PASS. 실제 `run.py → prepare → consult → SDK(mock) → DIAGNOSE` 2/2 PASS. H5는 ACTION 4 + PLAN 1 + REFRESH 1 + RECORD 1, H6는 ACTION 4 + AUDIT 1 + RECORD 1 경로를 확인했다. 이는 미리 지정한 mock 행동이며 실제 환자별 호출·턴 수 예측이 아니다.

로컬 전체 근거는 `nova_adaptive_coverage_20261022/`의 `validation-combined.json`, `checks/`, `checks-retry/`, `context_review/review.json`, `deliverables/manifest.json`에 있다. [RESULTS.json](RESULTS.json)에 경로·증거 해시·후보별 설정을 고정했다.
