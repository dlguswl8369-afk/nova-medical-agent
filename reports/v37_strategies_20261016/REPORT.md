# NOVA v3.7 — 독립 전략 후보 A/B/C

2026-10-16. 기준 `81714d340207a8e5ca9886dd2129cbd6b9cc61f2` (v3.5).
시작 상태는 `codex/nova-v3-6-communication`, `ddb8eeae4d7ee06955165bc157ce56c7f8ccdc40`, 미커밋 변경 없음이었다. 기준 커밋에서 새 `codex/nova-v3-7-strategy-experiments` 브랜치를 생성했다. v3.6 변경은 포함하지 않았다.

## 구현과 비교

| 후보 | 실제 실행 코드의 차이 | 기대하는 개선 / 주된 위험 |
|---|---|---|
| A Differential-Driven | 새 관찰 우선 + 최근 4개 관찰을 먼저 패킹. 병력 답변·진찰·검색 자료의 ID를 분리한 감별용 색인. 단일 STEP에서 지지/반박 근거와 답변에 따른 결정 변화를 비교하도록 지시 | 정보수집·감별·필요한 EXAM 선택. 초기 가설 고착으로 위험 확인을 줄일 위험 |
| B Clinical-Decision | 새 관찰 이후 실제 EXAM 결과 우선 패킹. 시행한 진찰, 미실시 TEST, 전송된 설명/환자 반응을 구분하는 결정용 색인 | 검사 목적·의뢰·추적 연결. 진찰 결과에 과도하게 의존하거나 추가 계획 설명으로 턴이 늘 위험 |
| C Patient-Centered | 새 관찰 이후 최근 환자 답변 3개와 최근 EXAM 우선 패킹. ASK/EXPLAIN과 환자 반응을 연결하는 대화 색인 | 실제 걱정·질문·부분 답변 대응과 설명 정확성. 최근 대화 편향과 설명 증가로 효율이 떨어질 위험 |

**첫 샘플검증은 A, 차선은 B를 추천한다.** A는 정보수집·감별에 집중하고 B는 검사·추적 의사결정을 분리해 볼 수 있다. C는 v3.5의 상대적 강점인 의사소통을 다시 바꾸므로 우선순위를 낮춘다. 이 순위는 코드·관측 한계에 따른 실험 우선순위이며 예상 점수가 아니다.

공통 실행부는 `State.strategy → Run.context → action_facts/decision_view → Run.doctor`에 연결되어 있다. ZIP은 `strategy_config.STRATEGY`를 A/B/C로 각각 고정하므로 외부 설정 없이 실행된다. 저장소 기본값 `baseline`은 v3.5 행동 프롬프트·컨텍스트를 선택하는 대조군이다. 코드 수준 선택은 `State(..., strategy='A')`와 같다. ZIP 간 차이는 이 선택 파일뿐이며 전략 코드는 공유한다.

단순 프롬프트 추가 외에 **원문 관찰의 예산 내 선택 우선순위와 모달리티·대화 연결 색인을 실행 시 계산**한다. 그러나 이 코드가 질환이나 위험 신호를 자체 판정하는 것은 아니다. 감별 갱신·미확인 항목 해석·다음 행동 선택은 기존 Doctor의 같은 호출 안에서 수행한다. 별도 요약/진단 호출, 가설 확률·review 필수 JSON, 강제 종료 상태 머신은 없다. 요약문으로 답변을 대체하지 않는다.

A/B/C 공통으로 ‘검사 계획은 최종 P에만’이라는 충돌을 해소한다. TEST 실행은 금지하고 미실시 계획을 P에 기록하되 필요하면 SAY로 설명한다. 이는 세 전략에 공통인 변경이므로 v3.5와의 차이를 전략 한 요소만의 인과효과로 해석하지 않는다.

## 보존과 비용

- `prompts.py` 전체(STEP 원본·RECORD), SDK, 모델/medium/출력 상한, Config, RAG 검색·쿼리·인덱스·검색 예산·캐시, 행동 30자/NFC/중복 검증, 재시도·시간 제한·토큰 원장은 v3.5와 동일하다. STEP 변형은 전략 모듈에서만 구성한다.
- RECORD 호출에는 전략 색인과 우선순위 변경을 전달하지 않고 v3.5 컨텍스트를 사용한다. 최종 기록 예약도 같은 컨텍스트로 계산한다. S/O 원문·관찰 ID 보존, SAY 성공 확인, 계획/전달/이해 구분은 기존 기능을 재사용한다.
- 기존 후보·로그·원장 등 15개를 이전 보존 해시와 읽기 전용 대조했다. [preservation.json](preservation.json). 원장 복제·초기화 없음.
- 추가 LLM 호출은 0회. 합성 동일 행동 흐름은 후보당 기존과 같은 5 Doctor 호출이다. 실제 모델이 선택할 턴 수·시간·토큰은 미확인이다.
- 기존 로그의 캡처 문맥에서 추가 STEP UTF-8 바이트는 A 1,190 / B 1,134 / C 1,159. 추가 ID 색인은 A 267–323 / B 336–413 / C 1,232–1,788바이트(빈 reference ID 목록 기준)였다. **토큰 수가 아니며**, 실제 비용은 기존 예산 원장에 포함된다. C의 대화 색인이 가장 크다.
- 공통 코드 규모는 작고 외부 의존성이 없다. A/B/C 모두 같은 22,000자 관찰 상한을 지키지만 장문에서는 기존 병력 대신 최근/전략별 관찰이 들어갈 수 있다. 모든 과거 위험 신호 보존을 보장하지 않으며 예산이나 RECORD 선택 정책은 바꾸지 않았다.

## 오프라인 확인

Python 3.12, socket/getaddrinfo/create_connection 차단. 실제 API 호출 없음; OS 격리 검증은 아니다.

- 관련 묶음 93개: 기존 85개 통과, 신규 8개 중 1개 픽스처 실패. 패킹 용량이 커 A/C 선택이 같았던 픽스처를 정확히 4개 관찰이 들어가는 경계로 수정했다. 실행 코드 변경은 없었다.
- 신규 전략 테스트만 8/8 재확인. 기존 전체 테스트를 반복하지 않았다. [초기 결과](offline_tests.json), [수정 후 결과](strategy_tests_fixed.json).
- ZIP 3개의 실제 run.py/prepare/consult를 SDK transport mock으로 각각 실행했다. ASK→EXAM→EXPLAIN→DONE→DIAGNOSE, 전략 선택, 5회 Doctor 호출, RECORD 분리 확인. [A](smoke_A.json), [B](smoke_B.json), [C](smoke_C.json).
- 기존 v3.2/v3.3 개발 API 로그 6건의 최종 캡처 관찰을 읽기 전용 재구성했다. 모두 예산에 들어가 원문·ID가 그대로 유지됐다. **원래 전체 진료 재실행이나 모델 행동 비교가 아니다.** 웹사이트 상세 로그·v3.5/v3.6 실제 로그는 사용하지 않았다.

| 확인 항목 | 오프라인에서 확인한 것 | 남은 한계 |
|---|---|---|
| 위험 신호 | 긴 합성 문맥에서도 최신 호흡곤란 답변 원문 보존 | 실제 위험 인식·적절한 안전 행동은 실제 모델 평가 필요 |
| 부분 답변 | 혼합 답변·질문 원문 유지, 자동 음성 분류 없음 | 모델 A의 임상적 확대 해석 방지는 실제 모델 평가 필요 |
| 질문 중복·설명 반복 | 동일 문구 차단 유지, 반응과 기존 설명 연결 | 동의어 반복·설명의 유용성은 실제 모델 평가 필요 |
| 감별·다음 ASK/EXAM | 전략별 컨텍스트·프롬프트가 실제 실행 경로에 들어감 | 적절한 선택 여부는 실제 모델 평가 필요 |
| 검사·추적 근거 | reference와 환자 ID 분리, TEST 거부, O.tests 비움 | 검사 목적·추적 시점의 임상 타당성은 실제 모델 평가 필요 |
| 실제 설명·기록 | 성공한 SAY만 전달로 기록, 거절 제외, 이해 미확인 유지 | 설명의 충분성·환자 이해는 실제 모델 평가 필요 |
| 형식·종료·예산 | 31자 거부·복구, 단순 JSON/DONE, 기록 예약·원문 보존 회귀 | 품질·안전 점수를 보장하지 않음 |

## 후보 ZIP

경로: `../nova_v37_strategies_20261016/deliverables/` (저장소의 형제 폴더).
모두 **44,992,696 bytes**, 45,000,000 bytes 미만이다. 26파일, 루트 run.py/requirements.txt/nova_sdk.py, 파일 해시·CRC·중복/탈출 경로 부재·해제 크기 조건 확인. [전체 명세](candidate_manifests.json).

| 후보 파일 | SHA-256 |
|---|---|
| nova_doctor_bm25_candidate_v3_7_A_differential_20261016.zip | `6ce8290614c360c4c307b1d8fc632877e71e5d1c12ecdfb3d1210c3d03d94690` |
| nova_doctor_bm25_candidate_v3_7_B_clinical_decision_20261016.zip | `2195dbea7d7e7bd720a5bf0006db45c450c839daa626e2fa8a3eeb16d5028486` |
| nova_doctor_bm25_candidate_v3_7_C_patient_centered_20261016.zip | `820ddeba79ee6a5ef5d8310da83ccac4b2ba74483705655719ea6044e144f154` |

v3.5 대비 실행 파일 변경: `app/nova_agent/loop.py`, 신규 `strategies.py`, 신규 `strategy_config.py`.
개발 파일: `tests/test_strategies.py`, `scripts/check_strategies_offline.py`, `scripts/package_strategies.py`, 본 보고서 폴더. ZIP·인덱스·원문·비밀정보를 새 Git 파일로 추가하지 않는다.

## 공개 구현과 라이선스

전체 설치·실행·데이터 다운로드 없이 핵심 공개 코드를 확인했다. 아래 아이디어를 독립 구현했으며 외부 소스·프롬프트·데이터를 복사하거나 패키지에 포함하지 않았다. 공개 벤치마크 성능을 NOVA 성능으로 환산하지 않는다.

| 출처 | 실제 확인한 구현 / 적용 범위 | 라이선스 확인 |
|---|---|---|
| Microsoft MeDxAgent | [DoctorQDiffAgent.execute](https://github.com/microsoft/MeDxAgent/blob/main/src/agents/doctor_q_diff_agent.py#L44), [DoctorQAgent.execute](https://github.com/microsoft/MeDxAgent/blob/main/src/agents/doctor_q_agent.py#L44): 감별 피드백·대화/이전 질문 참조. [SummarizerStrAgent.execute](https://github.com/microsoft/MeDxAgent/blob/main/src/agents/summarizer_str_agent.py#L43)는 별도 호출이므로 이식하지 않고 원문 ID 색인으로 대체. [실제 구성](https://github.com/microsoft/MeDxAgent/blob/main/configs/variations/medxagent.yaml)은 요약·감별 전환·질문 전달 등을 별도 설정한다. NOVA도 baseline/A/B/C를 독립 선택하지만 고정 전환 턴·확률 종료는 도입하지 않음 | 루트 LICENSE 조회 404, 저장소 화면에 라이선스 표시 없음. 재사용 허가를 확인하지 못했으므로 코드·프롬프트 복사 없음 |
| The-Swarm-Corporation Open-MAI-Dx-Orchestrator | [MaiDxOrchestrator._get_prompt_for_role / _run_panel_deliberation](https://github.com/The-Swarm-Corporation/Open-MAI-Dx-Orchestrator/blob/main/mai_dx/main.py#L535): 가설을 구분하는 다음 확인·결정 가치. 다중 호출, TEST 자동 변환, 신뢰도만의 강제 종료는 제외. Microsoft 공식 구현으로 취급하지 않음 | [MIT, 2023 Eternal Reclaimer](https://github.com/The-Swarm-Corporation/Open-MAI-Dx-Orchestrator/blob/main/LICENSE) |
| AgentClinic | [DoctorAgent.inference_doctor](https://github.com/SamuelSchmidgall/AgentClinic/blob/main/agentclinic.py#L481): 최근 환자 발화와 대화 연결. 고정 질문 횟수·TEST 프로토콜·자료 없는 검사 정상 응답은 제외 | [MIT, 2024 Samuel Schmidgall](https://github.com/SamuelSchmidgall/AgentClinic/blob/main/LICENSE.txt) |
| OpenAI simple-evals / HealthBench | [HealthBenchEval.grade_sample](https://github.com/openai/simple-evals/blob/main/healthbench_eval.py#L367): 대화와 항목별 판단 근거를 연결하는 검토 형식만 참고. LLM grader·점수 산정은 도입하지 않음 | [MIT, 2024 OpenAI](https://github.com/openai/simple-evals/blob/main/LICENSE) |

MIT 소스를 추후 복사·배포한다면 해당 저작권·허가 고지 보존 조건을 확인해야 한다. MeDxAgent의 불확실한 라이선스는 별도 확인이 필요하다. 접근 실패한 디렉터리 목록은 반복 탐색하지 않았다.

유료 API·새 진료·자가채점·웹사이트 검증·Linux 전체 재검증·Docker/GCP 설치·공식 제출·main 병합은 수행하지 않았다. 다음 단계는 사용자가 A ZIP으로 웹사이트 샘플검증을 하는 것이다. 실제 임상 품질과 점수 향상, 안전 15점 유지는 미확인이다.
