# v3.8 Clinical Coverage 후보 — 2026-10-21

기준 v3.5 `81714d340207a8e5ca9886dd2129cbd6b9cc61f2`의 미완성 작업을 `codex/nova-v3-8-clinical-coverage`에서 이어 완성했다. 하네스는 별도 checkout의 `93abcdcdef146a0ade5a55c0ae5b4b70a7a0bb2c`를 그대로 사용했고 수정하지 않았다. 실제 임상 품질·정보수집/의사소통 점수·안전 유지 여부는 미평가다.

## 이어받은 작업과 실행 차이

| 위치 | v3.5 대비 후보 동작 / 이번에 완성한 부분 |
|---|---|
| app/nova_agent/coverage.py | 이어받은 관찰 ID 색인과 선택적 `next_focus` 유지. 문진 응답·실시 EXAM·전달 EXPLAIN·제공 활력·빈 응답·생략 ID를 구분한다. 부분 답변/모름을 임상 상태로 분류하지 않는다. 추가한 `action_facts`는 같은 fact_chars 안에서 초기 정보, 최신 환자 응답 쌍, 최근 진찰을 우선 담고 기존 관찰을 채운다. 문장은 자르거나 요약하지 않는다. |
| app/nova_agent/loop.py | 실제 ACTION 컨텍스트에 위 색인을 연결한 기존 작업을 유지했다. 최신 답변/진찰 선택을 ACTION에만 적용하고, v3.5 선택으로 만든 `record_user`와 최종 RECORD 입력은 유지했다. SDK 성공 이후에만 선택적 메모를 저장하며 다음 행동 선택 한 번 뒤 소모한다. 메모는 관찰·검색·최종 기록으로 승격하지 않는다. 원문 없는 ID/바이트 감사 정보만 추가한다. |
| app/nova_agent/prompts.py | 이어받은 주호소별 필요한 확인, 위험·필수 진찰 우선, 실제 걱정/질문·이해 곤란 대응, 실제 SAY 안내와 DONE 전 누락 검토 지침 유지. 최신 환자 발화 ID와 빈 응답의 의미를 명확히 했다. '검사 계획은 P에만' 충돌을 해소해 미실시 계획을 필요하면 SAY로 설명하게 한다. RECORD 문자열은 v3.5와 동일하다. |

`next_focus`는 240자 이하 선택적 문자열이며 없거나 잘못되어도 행동·DONE을 거부하지 않는다. 작성 시점의 컨텍스트 ID와 이후 실제 응답 ID를 붙여 새 응답 이전의 의도임을 구분한다. 임상 완료 상태·필수 review JSON·정규식 의미 판정·고정 문진/설명 횟수·DONE 차단은 추가하지 않았다. 질문했다는 사실은 답변 확보를 뜻하지 않고, 설명 성공도 이해 입증이 아니다.

시작 시 HEAD/브랜치와 세 파일 diff를 확인했다. 초기 미커밋 파일과 tracked diff는 Git 밖 `nova_v38_clinical_coverage_20261021/inherited_work/`에 보존했고 초기 해시 일치를 확인했다. 초기/완료 해시는 [validation.json](validation.json)에 있다. reset·기존 변경 폐기 없이 해당 설계 위에 보완했다.

그 외 app 22개 파일은 v3.5 바이트와 동일하다. gpt-6-luna medium, 모델 출력 한도, RAG/지침 검색·인덱스, SDK, 예산·종료/재시도 계약, RECORD 및 원문 기록 조립은 유지한다. TEST 금지·NFC 30자·자동 절단 금지·금지 행동의 EXAM 변환 금지도 그대로다. 별도 검토/진단 모델 호출은 없다.

## 검증과 10개 사례

최신 하네스의 기존 명령으로 변경 관련 회귀 **61개 첫 실행 PASS**: 행동·관찰·설명 36(기존 30 + v3.8 공백 6), 기록·예산 14, 원장/예산 4, 형식 복구 2, 평가자 분리 5. 후보 범위 REVIEW, 보호 AST PASS, 검사 전후 app 보존 PASS. 하네스 전체를 반복하거나 확장하지 않았다.

기존 `review` 실행에서는 원본 해시/근거를 확인하고 임상 사례 10개를 모두 REVIEW로 유지했다. 추가로 같은 보존 관찰을 후보 `Run.context`에 넣어 원문 보존·실시 ID 구분·RECORD 분리를 확인했다. 이는 **과거/합성 입력의 컨텍스트 투영**이며 v3.8 모델 진료나 새 환자 세션이 아니다. 공개 대본·진찰표·모범 기록을 Doctor에 넣지 않았다. 상세 출처와 ID는 [review_cases.json](review_cases.json).

| 사례 | 자동 확인 | REVIEW / 미평가 |
|---|---|---|
| 주호소 문진 누락(합성) | 확보 관찰만 유지 | 중요한 추가 문진 선택 |
| 필요한 진찰 미실시(C01 v3.2) | EXAM 없는 로그에 실시 ID를 만들지 않음 | 필요한 진찰·시점 |
| 부분 답변 확대(C03 v3.3) | 원문 쌍을 음성으로 재작성하지 않음 | 모델 A의 확대 해석·필요한 재확인 |
| 이미 답한 질문 반복(합성) | 원문과 기존 동일 행동 보호 유지 | 다른 표현의 중복·재확인 필요성 |
| 직접 질문 미응답(합성) | 최신 환자 응답 원문/ID 가용성 | 실제 응답하는 다음 행동 |
| P와 실제 설명 차이(C03 v3.3) | 실제 EXPLAIN ID와 RECORD 입력 구분 | 필요한 추적·악화 안내가 충분한지 |
| 위험 확인 지연(합성) | 원문 주호소 보존, 상태 추정 없음 | 위험 인식과 행동 우선순위 |
| 반복 설명(C03 v3.3) | 설명·환자 반응 쌍 보존 | 설명의 추가 가치·이해 여부 |
| 유효한 재확인(C10 v3.3) | 부분 답변과 후속 응답 함께 보존 | 임상적으로 필요한 재확인 |
| 기존 합성 예시 | 부분/이해 곤란 응답 보존 | 적절한 질문과 설명 선택 |

신규 회귀는 예산 압박에서 최신 응답·진찰이 실제 ACTION 입력에 남는지, 너무 큰 쌍을 자르지 않고 생략 표시하는지, 메모가 1회만 전달되고 RAG/RECORD에 섞이지 않는지, 전송 거절 후 가짜 설명/메모가 생기지 않는지, 메모 오류가 행동/DONE을 막지 않는지, 빈/모름/부분 답변 원문을 유지하는지를 확인한다. 나머지 실행 계약은 기존 테스트를 재사용했다.

ZIP 추출본의 실제 `run.py`·SDK·기존 legacy RAG를 사용한 네트워크 차단 mock smoke도 PASS. ASK→EXAM→EXPLAIN→DONE→DIAGNOSE, ACTION coverage 포함, RECORD 제외, 4회 행동 선택+기존 기록 1회 호출, 원문 보존과 설명/이해 구분을 확인했다. [candidate_smoke.json](candidate_smoke.json). 실제 모델·세션 API, 웹사이트 평가·공식 제출, Docker/GCP/Linux 재검증은 하지 않았다.

## 비용·위험

- STEP은 v3.5보다 1,447 UTF-8바이트 늘었다. 10개 보존/합성 컨텍스트의 추가량은 284~414바이트였다(선택 메모 없음). 메모와 긴 진료에서는 달라진다. 바이트는 실제 토큰이나 시간 측정값이 아니다. 별도 호출을 추가하지 않았어도 실제 행동 수·비용은 바뀔 수 있다.
- 같은 관찰 예산에서 최신 응답·진찰을 우선하면 일부 오래된 병력이 ACTION 창에서 빠질 수 있다. 생략 ID를 알리고 원문 원장과 v3.5 RECORD 선택/조립은 유지하지만 임상적 손실 가능성은 남는다. 단일 원문 쌍이 예산보다 크면 그대로 생략되며 분할하지 않는다.
- 선택 메모는 모델의 불완전한 의도일 수 있다. 한 번만 사용하고 새 응답을 우선하도록 했지만 잘못된 가설 고착을 완전히 방지하지 않는다. 메모·색인·지침만으로 누락 감소나 안전 점수를 보장하지 않는다.
- DONE 자유 선택과 기존 예산 보호를 유지하므로 중요한 확인/설명 없이 종료할 가능성도 남는다. 이번 테스트로 충분한 문진·진찰·설명을 입증했다고 해석하지 않는다.

## 산출물

- ZIP: `nova_v38_clinical_coverage_20261021/deliverables/nova_doctor_bm25_candidate_v3_8_clinical_coverage_20261021.zip` (저장소의 상위 작업 폴더 기준)
- 크기: **44,991,725바이트**, 45,000,000바이트 미만. 해제 95,118,280바이트, 25개 파일.
- SHA-256: `5c3999e4d1198b1eec4e55654f910c107aacabe9747fe714385a7f89c273e03f`
- 기존 제출 루트 구조, 중복/경로 탈출 없음, CRC, 파일별 해시 및 작업 app 일치 확인: [candidate_manifest.json](candidate_manifest.json). ZIP은 Git에 포함하지 않는다.
- 변경 파일: 진료 코드 3개, `tests/test_simple_v35.py`, 이 보고 폴더의 근거 JSON 4개 및 REPORT.md. 기존 후보·원본 로그·원장·하네스는 수정하지 않았다. 실험 브랜치에만 커밋·푸시하며 main은 병합하지 않는다.

하네스 폴더에서 사용한 명령(Python 3.12; 이 PC에서는 기존 `nova_rag_dev_20261015/doctor_agent_v2/validation/python312/python.exe`):

```powershell
python -X utf8 -B -I scripts/dev_harness.py check --repo ../nova-medical-agent --baseline v3.5 --candidate --group action_observation_delivery --group final_record_budget --group accounting --group repair --group evaluator_separation
python -X utf8 -B -I scripts/dev_harness.py review
```

실제 성능 검증은 사용자의 별도 결정 후 진행한다. 이번에는 실행하지 않았다.
