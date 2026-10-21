# H1–H4 임상 검토 범위

기준은 v3.5 `81714d340207a8e5ca9886dd2129cbd6b9cc61f2`, 검토 카탈로그는 별도 하네스 `93abcdcdef146a0ade5a55c0ae5b4b70a7a0bb2c`의 `harness/cases/clinical_review.json`이다. 아래는 기존 10개 사례의 **검토 설계**이며 신규 모델 실행 결과가 아니다. 모든 H1–H4의 임상 성능·안전 점수·80점 달성 여부는 **NOT_EVALUATED**다.

과거 개발 로그는 v3.2/v3.3이며 웹사이트 H1–H4 trace가 아니다. 공개 샘플의 환자 대본·진찰표·참고 기록은 평가자 전용이다. 이번 파일은 원문을 복제하지 않고 기존 출처 ID와 JSON 포인터만 연결한다. 사용자 제공 V1/V2/V3/V4 집계 54.31/58.37/53.53/60.73은 원인 규명 근거가 아니다.

| 기존 사례 ID | 기존 근거 | 연결되는 새 경로 | 자동 검증의 범위 / 남는 사람 판단 |
|---|---|---|---|
| complaint-history-gap | 합성 `/history_gap` | H1 계획·H3 종료 검토·H4 | 계획이 미시행 사실로 저장되지 않는지 / 증례별 필요한 문진은 REVIEW |
| unperformed-exam | C01-v3.2 `/events`, `/report/termination_reason`; C01-public `/exam_results/1`은 평가자 전용 | H2 진찰 선택·H3·H4 | SDK 성공한 EXAM만 O로 기록 / 어떤 진찰이 필요한지는 REVIEW |
| partial-answer-overclaim | C03-v3.3 F8 및 `/final/note/A/differential` | H1 계획 수정·H2·H3·H4 | 질문·답변 원문과 ID 보존 / A가 답변 범위를 넘었는지는 REVIEW |
| already-answered-repeat | 합성 `/repeated_answer` | H1·H2·H4 | 동일 성공 행동의 중복 전송 방지 및 이력 보존 / 필요한 재확인인지 REVIEW |
| patient-question-unanswered | 합성 `/direct_question` | H1·H3·H4 | 감사 제안이 실제 SAY 성공 전 설명으로 집계되지 않음 / 응답의 적절성·긴급 우선순위는 REVIEW |
| record-plan-vs-spoken | C03-v3.3 `/final/note/P/follow_up`, F20–F22 | H3·H4 | 실제 SAY와 P 계획의 저장 경로 분리 / 동등한 의미와 설명 필요성은 REVIEW |
| risk-assessment-delay | 합성 `/risk_delay` | H1 계획 실행 시점·H2·H3·H4 | 첫 행동 전 계획 호출 금지 및 현재 응답 이후 readiness 사용 / 위험 인식과 적절한 응급 행동은 REVIEW |
| similar-explanation-repeat | C03-v3.3 F20–F22 | H1·H3·H4 | 실제 설명·환자 반응 원문 보존, 감사 한 번 제한 / 반복 설명의 임상적 필요성은 REVIEW |
| needed-clarification-control | C10-v3.3 F17·F18 | H1·H2·H3·H4 | 미답변이 관찰 음성으로 변환되지 않음 / 유효한 추가 문진을 중복으로 오판하지 않는지는 REVIEW |
| existing-example-partial-and-understanding | 합성 example T1·T2, 최종 기록 없음 | H1·H3·H4 | 전송 성공과 이해 확인 분리 / 전체 진료·최종 기록 부족 부분은 NOT_EVALUATED |

## 보존할 실행 불변조건

- 계획·계획 수정·종료 감사는 환자 관찰이 아니다. 계획에는 관찰 ID를 참고할 수 있지만 S/O 원문이나 실제 설명 목록에 편입하지 않는다. RECORD는 기존 관찰·참고자료 경로만 사용한다.
- 계획 허용 신호는 그 신호를 생성한 Doctor가 본 관찰 범위에서만 유효하다. 새로운 환자 답변이 온 뒤 이전 신호로 추가 호출하면 새 위험 신호 확인을 지연할 수 있다. 위험 여부 자체를 정규식으로 확정하지 않는다.
- 감사의 ASK/EXAM/EXPLAIN 제안도 기존 행동 파서와 SDK 성공 검사를 거친다. 거부된 EXAM은 O에 넣지 않고, 거부 코드를 다음 선택에 제공한다. TEST를 EXAM으로 바꾸지 않는다.
- 감사는 첫 DONE에서 최대 한 번 시도한다. 충분함·형식 오류·예산 부족·시간 부족·일시 오류 시 원래 DONE으로 돌아갈 수 있어야 한다. 이는 임상적으로 충분했다는 판정이 아니다.
- 추가 호출도 기존 원장에 입력 추정량·추론을 포함한 출력 한도·HTTP 횟수를 예약한다. 기존 최종 RECORD 재시도와 시간 여유를 유지하고, 한 번 실패한 보조 호출을 자동 재생성하지 않는다.
- 마지막 DIAGNOSE는 정상·기록 fallback 경로에서 시도한다. 세션 만료·서버 종료·네트워크 장애에서도 접수가 보장된다고 표현하지 않는다.

## 검증의 한계와 비용 위험

기존 `scripts/clinical_review.py:46`의 로그 결합은 SDK 성공 이벤트만 관찰과 연결하며 실패 시도 전체를 복원하지 않는다. `:93`의 Doctor projection은 평가자 필드를 제외하고, `:127`의 분석은 문자 보존·행동 실행 사실을 추출한다. 의미상 문진 충분성, 새 답변에 따른 가설 수정, EXAM 필요성·적절성, 환자 질문 응답의 질, 설명 의미·환자 이해, 안전한 DONE은 자동 PASS 대상이 아니다.

H1의 계획은 가설 고착·낡은 계획 유지 위험이 있다. H2는 불필요한 진찰 또는 거부되는 구체성의 행동을 늘릴 수 있다. H3는 중요 누락을 놓치거나 이미 충분한 진료를 불필요하게 연장할 수 있다. H4는 이 위험들과 비용을 결합하며 성능이 단순 합산되지 않는다. 같은 모델의 독립 검토는 별도 역할의 호출일 뿐 독립적인 임상 전문가나 외부 검증이 아니다.

기존 `fact_chars` 선택 범위를 유지하면 길어진 진료에서 중요한 과거 관찰이 ACTION/감사에 모두 보이지 않을 가능성도 남는다. 보조 호출의 1회/2회 상한은 추가 **호출** 상한이며, 감사가 유도한 추가 진료의 ACTION 호출·SAY/EXAM 턴·총 지연을 1회/2회로 제한한다는 뜻은 아니다. 실제 지연·토큰 사용량과 환자별 의사결정 질은 모델 실행 없이 확인할 수 없다.

## 읽기 전용 컨텍스트 투영 결과

`scripts/review_high_intensity.py`를 한 번 실행했다. 기존 로컬 출처 20개 해시 검증과 10개 사례 × BASELINE/H1/H2/H3/H4의 50개 투영은 PASS다. SDK 성공과 연결되거나 합성 trace에서 명시적으로 승인된 관찰만 사용했다. 관찰 원문·ID·참고자료·RECORD 입력은 모두 baseline과 같았고, 이 10개 사례의 선택 누락은 0개였다. 미래의 긴 trace에서 누락이 없다는 증명은 아니다.

계획이 없는 ACTION 입력 증가는 H1 +743, H2 +837, H3 +288, H4 +1,292 UTF-8 바이트였다. 36자 합성 계획 표시를 별도로 넣으면 ACTION만 75바이트 증가하고 관찰·RECORD는 그대로였다. 실제 생성 계획의 길이·토큰 비용은 측정하지 않았다. 보조 입력도 기존 사실 컨텍스트로만 구성하고, PLAN 3,072 / AUDIT 3,072 / 여유 있는 H4 AUDIT 4,096 출력 한도와 조건부 high 설정을 확인했다. 이는 추론을 포함한 예약 상한이며 실제 토큰 사용량이 아니다.

출력 근거는 작업 디렉터리 외부 `nova_high_intensity_experiments_20261022/context_review/review.json`에 있으며 원본 대본·로그를 복제하지 않았다. 모든 임상적 적절성은 REVIEW, 새 후보 임상 성능은 NOT_EVALUATED다. 이 투영에서는 모델 호출·신규 진료·행동 생성을 실행하지 않았다. 실행 경로 회귀와 ZIP 진입점 결과는 별도 검증 보고서에서 구분한다.
