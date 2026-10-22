# H7 Closed-Loop Clinical Executor · 2026-10-22

v3.5 `81714d340207a8e5ca9886dd2129cbd6b9cc61f2`에서 직접 분기한 실행 정책 실험이다. **임상 성능·점수·80점 달성 여부는 NOT_EVALUATED**다. 확인한 H5/H6 자료는 코드와 오프라인 검증이며 실제 웹사이트 실패 원인을 입증하지 않는다. H5/H6에서 계획/대안이 실제 목표 이행으로 연결되지 않던 구조적 한계를 겨냥했다.

## 실제 변경

첫 성공 행동 후 최신 답변을 읽은 Doctor가 긴급 행동을 표시하지 않은 시점에 GOALS를 최대 한 번 호출한다. 목표는 ID·ASK/EXAM/EXPLAIN·중요도·이유·조건·실제 관찰 ID·NFC 30자 이하 행동으로 구성한다. 최대 8개는 저장 상한이며 필수 문진·진찰 수가 아니다. 충분하면 빈 목표를 허용한다. 첫 행동부터 DONE이면 초기 확인을 억지로 만들어내지 않고 기존 종료를 허용한다.

`GoalExecutor`는 목표 버전과 실행 영수증을 세션별로 보유한다. 실제 SDK 행동과 목표의 유형·문장이 일치하고 응답 검증·관찰 삽입까지 성공해야 `performed`와 관찰 ID가 저장된다. 실패·거부는 `failed`, 아직 하지 않은 행동은 `pending`이다. **ASK의 performed는 질문 전송과 응답 수신만 뜻한다. 병력 확인·임상적 충분성·환자 이해는 완료로 바꾸지 않는다.** 원문 응답을 별도로 보존하며 모든 목표의 임상적 충분성은 REVIEW다.

새 응답·실패마다 revision이 바뀐다. 이후 ACTION의 `goal_review`가 현재 revision에서 필요한 목표를 다시 지정해야 DONE 보류에 사용할 수 있다. 새 증상 때문에 부적절해진 목표는 withdraw하고, 부분 답변의 필요한 나머지는 새 문장·근거·조건으로 revise할 수 있다. 이전 실행 영수증은 버리지 않는다. 모델의 `completed` 주장이나 잘못된 goal_id는 수행 증거로 사용하지 않는다.

DONE일 때 현재 필요하다고 재확인된 critical/important 미수행 목표가 있고 시간·예산 여유가 있으면 하나를 실제 SDK로 실행한다. 초기 계획 직후에는 그 계획의 현재 필요성 판단을 사용한다. **보완 선택 최대 6회**, 실패한 시도도 상한에 포함된다. 성공·실패 뒤에는 다시 평소 ACTION 호출로 환자 반응과 남은 목표를 검토한다. 별도 종료 감사 호출은 없다. 같은 성공/거부 행동의 정확한 문장은 재실행하지 않는다.

다음에는 DONE을 허용한다: 충분함, 현재 필요한 목표 없음, 오래됐거나 잘못된 재검토, optional 목표만 남음, 실행 가능한 새 행동 없음, 긴급 우선, 자원 부족, 보완 6회 도달. 목표 상태 때문에 유효한 일반 SAY/EXAM을 거부하지 않는다. 일반 행동도 실제로 목표 행동과 일치하면 SDK 성공 후 연결한다.

## 파일과 보호 정책

| 변경 파일 | 범위 |
|---|---|
| `app/nova_agent/closed_loop.py` | 새 목표 저장·수정·현재 필요성 검토·DONE 보완 선택·SDK 영수증 연결 |
| `app/nova_agent/loop.py` | H7 경로, GOALS 한 번, ACK 이후 기록, 실패 기록, 보완 및 시간/예산 admission |
| `app/nova_agent/experiment_config.py` | 저장소 기본 BASELINE, 후보 ZIP은 H7 고정 |
| `scripts/check_h7.py`, `tests/test_h7_policy.py` | 기존 하네스 재사용; 좁은 Config/Doctor/action 시간 보호 예외 검사 |
| `tests/test_h7.py`, `scripts/package_h7.py` | 실행·반사실적 회귀와 압축 해제 진입점 비교 |
| 이 보고서, `RESULTS.json` | 식별자·검증 근거·한계 |

RECORD 문자열·원문 S/O 조립·모델·SDK 파일·RAG 자료/검색/예산·토큰 원장은 v3.5와 같다. `prompts.py` 파일은 그대로지만 ACTION은 H7 지침을 붙여 사용한다. 목표·조건·미실행 행동·실패 이력은 ACTION 전용 별도 컨텍스트이며 RAG 질의·환자 관찰·RECORD에 넣지 않는다. 시험/원문/모범 기록은 ZIP에 포함하지 않는다. TEST와 명시적 TEST→EXAM 변환, 자동 30자 절단은 허용하지 않는다.

하네스 `93abcdcdef146a0ade5a55c0ae5b4b70a7a0bb2c`는 변경하지 않았다. 원래 보호 심볼 중 `Config.max_turns`의 H7 조건부 40, `Run.doctor`의 단일 GOALS 호출 및 H7 재시도 시간 확인, `Run.action`의 H7 재시도 시간 확인만 정확한 AST 변환으로 허용했다. 다른 모델/SDK/시간 계산/예산/기록 보호를 해제하지 않았다. 기존 worker의 네트워크·하위 프로세스·출력 외 쓰기 차단을 사용했다.

## 실행·비용·위험

- H7 ZIP만 **40턴**, 충분하면 조기 종료. Doctor 상한 **80회**, 입력 **500,000**, 출력 **100,000** 유지. 모델 `openai/gpt-6-luna`, 모든 호출 medium.
- ACTION 출력 상한 2048, GOALS/RECORD 4096. GOALS는 추론을 포함한 출력 최대 4096, 전송 한 번, 재시도 없음, 타임아웃 120초.
- 별도 보조 모델 호출은 최대 **1회**다. 보완 이후 일반 ACTION 호출이 최대 6회 추가될 수 있고, 일반 행동 증가·형식 복구·재시도 비용은 별도다. 모든 호출은 같은 80회/토큰 예산을 사용한다.
- 최종 기록 최대 3회 예산을 기존 방식으로 예약한다. 보완 전에는 다음 ACTION 1회와 기록 예약의 동시 여유도 읽기 전용으로 확인한다. 새 응답 크기는 미리 알 수 없어 실제 수신 후 원래 기록 envelope를 다시 계산한다.
- H7은 비최종 모델/SDK 요청·재시도 직전 남은 시간이 **540초 이하**이면 중단하여 최대 240초 요청 뒤에도 기존 300초 기록 여유를 보호한다. DIAGNOSE/최종 RECORD에는 이 비최종 gate를 적용하지 않는다. 서버 만료·네트워크 장애·타임아웃 초과에서도 최종 접수가 보장되는 것은 아니다.
- 구조화 목표와 반복 컨텍스트가 입력 비용을 늘리고, 실제로 불필요한 보완을 하면 효율이 하락한다. 목표 생성 실패·검토 누락·revision 오류면 기존 경로로 복귀하므로 효과가 약해질 수 있다.
- 현재 필요성·조건·긴급성은 모델 판단이다. 코드가 임상적 의미를 확정하지 않는다. 잘못된 목표를 재확인하면 불필요한 행동을 강행할 위험이 있다. 의미가 같은 다른 표현의 반복·부정확한 A 추론·중요 과거 관찰의 기존 fact_chars 제한도 남는다. 정확히 다른 문장으로 수행한 의미상 동일 행동은 자동 완료 연결하지 않으며 모델의 철회/수정이 필요하다.

## 검증과 반사실적 증거

**서로 다른 검사 82개 PASS**: 기존 관련 55개는 한 번 실행했고, H7/정책 27개는 TEST 충돌 및 재시도 시간 여유 보완 후 관련 묶음으로 검증했다. 전체 테스트를 반복하지 않았다. 최초/표적/최종 결과와 해시를 모두 보존했다.

반사실적 fixture는 최초 질문 뒤 행동 선택 Doctor가 **항상 DONE**만 출력한다. 목표 생성과 현재 필요성 판단은 합성으로 고정한다. 동일 H7에서 `GoalExecutor.choose`만 비활성화한 대조군과 활성군을 비교한다. 따라서 후속 행동을 ACTION mock에 직접 지정한 단순 전송 시험과 구분된다. 다만 임상 목표·필요성은 여전히 mock이므로 임상 선택 능력의 증거는 아니다.

| 경로 | 최초 질문 뒤 실제 행동 | 목표 상태 | 최종 기록 |
|---|---|---|---|
| v3.5 실행 경로 | 없음, DONE | 목표 없음 | 최초 관찰만 |
| H7 실행기 비활성 대조 | 없음, DONE | 세 목표 pending | 미수행 EXAM/설명 없음 |
| H7 활성 | ASK → EXAM → EXPLAIN, 보완 3회 | SDK 성공 관찰 F3/F4/F5에 연결 | 부분 답변·진찰 원문·실제 SAY 설명 보존 |

개별 회귀는 SDK 거절의 미완료 처리, 새 응답에 의한 목표 철회, 오래된 검토의 보류 금지, 부분/빈 답변의 비확정과 필요한 재확인, 모델 완료 주장 무시, 긴급 우선, 충분한 DONE, 6회 상한, 실패한 설명·미시행 진찰의 기록 제외, NFC 30자·TEST·예산·시간·세션 독립성과 실패 fallback을 검증했다. **임상적 적절성은 REVIEW, 실제 점수는 NOT_EVALUATED**다.

## 사용·보존

Python 3.12, 저장소 루트에서 새 출력 경로를 사용한다.

```powershell
$py = '../nova_rag_dev_20261015/doctor_agent_v2/validation/python312/python.exe'
& $py -X utf8 -B -I scripts/check_h7.py --output ../nova_h7_closed_loop_20261022/checks-new
& $py -X utf8 -B -I scripts/package_h7.py --output ../nova_h7_closed_loop_20261022/zip-new --validation ../nova_h7_closed_loop_20261022/checks-new/validation.json
```

브랜치 `codex/nova-h7-closed-loop-executor`. 기존 v3.8, V1–V4, H1–H4, H5/H6, 하네스 작업 디렉터리와 후보 ZIP·로그·원장은 그대로다. 원장은 초기화·복제하지 않았다. 실제 모델 API·새 진료·웹사이트 평가·제출·main 병합·설치는 실행하지 않았다. Git에는 코드·스크립트·테스트·간단한 보고서만 추가한다.

## 최종 후보

| 최종 ZIP | 바이트 | SHA-256 |
|---|---:|---|
| [nova_doctor_bm25_candidate_H7_closed_loop_executor_20261022.zip](<C:/Users/hjlee/OneDrive/문서/ChatGPT/의료 ai agent/nova_h7_closed_loop_20261022/deliverables-final/nova_doctor_bm25_candidate_H7_closed_loop_executor_20261022.zip>) | 44,994,662 | `f52afc5be90c7a5b8b2ac2f2d02ff52f0f5b2846348bab0be917c861f7951a6e` |

루트 `run.py`·`requirements.txt`, 26개 파일, 45MB 미만, CRC·구문·기준 파일 동일성·압축 해제 후 해시 검사 PASS. 실제 진입점 `run.py → prepare → consult → SDK(mock) → DIAGNOSE`에서 H7 활성 및 실행기 비활성 대조 모두 PASS. 활성군은 ACTION 5 + GOALS 1 + RECORD 1, 대조군은 ACTION 2 + GOALS 1 + RECORD 1이었다. 각 경로는 새 실행 상태와 mock 원장을 사용하며 기존 실제 원장을 복제하지 않았다.

[RESULTS.json](RESULTS.json)에 목표별 실행 영수증·DONE 결정·검사 파일 해시·후보 설정을 고정했다. 전체 근거는 `nova_h7_closed_loop_20261022/validation-final.json` 및 `deliverables-final/manifest.json`에 있다. `deliverables/`는 시간 보호 보완 전 내부 체크포인트이며 최종 후보는 위 `deliverables-final/` ZIP 하나다.
