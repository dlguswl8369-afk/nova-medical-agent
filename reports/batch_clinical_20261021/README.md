# NOVA 독립 비교 후보 V0–V4

기준 `81714d340207a8e5ca9886dd2129cbd6b9cc61f2`에서 별도 worktree/브랜치 `codex/nova-batch-clinical-experiments`를 만들었다. v3.6~v3.8 코드는 포함하지 않았다. 기존 v3.8 작업 디렉터리와 하네스(`93abcdcdef146a0ade5a55c0ae5b4b70a7a0bb2c`)는 그대로 보존했다. 최종 후보를 선택하지 않았다.

| 후보 | 실제 ACTION 경로의 독립 변경 | 기대하는 도움 / 미확인 위험 |
|---|---|---|
| V0_baseline | 기존 v3.5 ZIP 원본 재사용; 모든 파일을 기준 Git blob과 대조 | 비교 기준. 기존 한계도 유지 |
| V1_clinical_rag | 기존 근거 중 관련 임상 자료를 앞에 배치. 여유가 있을 때만 완결된 임상 근거 추가 | 다음 질문·진찰·계획의 참고 근거 강화 가능. 어휘 기반 순위 편향·무관한 추가 근거 위험 |
| V2_clinical_interview | 같은 관찰 ID·질문·답변·진찰 원문을 손실 없는 표로 구성. 최근 문진과 시행 진찰을 앞에 배치하고 짧은 문진 지침 교체 | 부분 답변 대조·진찰 확인 지원. 실제 미확인 항목 판단은 모델 몫이며 표/순서가 주의를 왜곡할 수 있음 |
| V3_communication | 최근 환자 응답과 실제 EXPLAIN/응답 쌍을 앞에 배치. 모두 보이는 경우에만 중복 설명 목록 제거. 실제 SAY와 P의 충돌 지침 수정 | 직접 질문·이해 곤란·아직 필요한 계획 설명에 주의 유도. 설명 턴 증가 및 문진 지연 가능성은 실제 평가 필요 |
| V4_integrated | V1 검색 + V2/V3의 우선순위를 하나의 관찰 표에 통합. 각 원문은 한 번만 표시 | 통합 효과와 간섭 모두 미확인. 토큰·행동 비용이 각 기능 효과의 합이라고 가정하지 않음 |

**공통 보호:** 관찰 선택 자체(`visible_facts`), 원문 원장, RECORD 프롬프트·입력·생성, 모델 gpt-6-luna medium, SDK, 기존 774개 RAG/지침 인덱스, 검색 근거 12,000자 및 토큰·호출·턴 예산은 유지했다. TEST 금지·NFC 30자·전송 성공 후 설명 기록·이해 여부 미확정·최종 기록 예산 확보도 유지한다. 추가 LLM 호출은 0회다. 고정 문진표·설명 횟수·DONE 차단·review JSON·coverage/next_focus는 없다.

V1/V4는 기존 검색 질의와 baseline 패킷을 먼저 유지한다. 이미 주제에 맞는 완결 임상 단위가 있으면 재검색하지 않는다. 없고 공간이 남는 경우에만 새 질의당 최대 한 번의 로컬 검색을 추가하며 세션 내 직전 질의는 재사용한다. baseline 근거를 제거하거나 잘라내지 않는다. 주제 연결·자료 역할·출처 해시·완결 단위·남은 공간 조건을 충족하지 못하면 기존 결과로 돌아간다. 기존 패킷이 꽉 차면 기존 단위의 순서만 바꿀 수 있다. 문서 순위용 어휘 검사는 환자의 임상 상태를 판정하는 검사가 아니다.

**변경 파일:** 앱은 `loop.py`(ACTION에만 연결), `experiments.py`(세 기능), `experiment_config.py`(ZIP별 고정 V1~V4) 3개뿐이다. 저장소 기본 설정은 V0이며 ZIP은 추가 설정 없이 해당 전략으로 실행된다. `prompts.py`, `context.py`, `record.py`, SDK·예산·인덱스는 바이트 단위로 v3.5와 같다. 개발 파일은 `scripts/{check_batch,compare_batch,package_batch}.py`, `tests/test_batch_experiments.py`, 기존 `tests/test_extension.py`의 임시 경로 1줄, 이 보고서와 검증 요약이다.

**검증 의미:** 공통 회귀, 전략별 기계적 검사, ZIP의 실제 `run.py`+SDK transport mock을 구분했다. 기존 하네스의 네트워크/프로세스/출력 폴더 밖 쓰기 차단을 그대로 사용했다. 별도 배치 정책은 앱 변경을 위 3개 파일로 더 좁히고 기존 보호 AST를 검사한다. 이는 악성 코드용 OS 격리나 임상 적절성 검증이 아니다.

10개 사례는 과거 v3.2/v3.3 개발 trace와 합성 문맥이다. 현재 후보의 진료 결과가 아니다. 공개 3건은 시작 발화·제공 활력만 검색 비교에 사용했다. 환자 대본·숨겨진 진찰 결과·모범 기록을 Doctor 입력으로 넣지 않았다. 동일 trace에서 원문/ID 보존, 동일 RECORD 입력, 실제 설명/반응 구분은 자동 확인하지만 문진·EXAM의 충분성, 위험 확인의 시급성, 질문의 가치, 설명의 적절성과 실제 이해는 REVIEW다. 새 모델이 선택할 행동·실제 점수는 NOT_EVALUATED다.

**입력·비용 비교:** 공개 시작 문맥 3건에서 V1은 legacy 검색 그대로, 지침 병용 시에는 기존 완결 단위 순서만 변경했다(새 근거 추가 0개). 추가 단위 선택 경로는 합성 지침/실제 검색 코드로 따로 검증했다. 초기 입력의 STEP+user UTF-8 바이트 차이는 V1 +0, V2 +318, V3 +359, V4 +420이다. 기존 10개 trace 투영에서는 V2 −711~+297, V3 −891~+338, V4 −830~+399바이트였다(빈 검색 통제). 이는 실제 과금 토큰 수가 아니다. 설명·질문 선택에 따라 실제 행동 수와 시간이 늘 수 있고, V1의 추가 근거가 들어오면 같은 근거 예산 안에서도 입력 비용이 늘 수 있다.

초기 비교에서 기존 임상 단위가 있는데도 두 번째 검색을 수행해 지침 병용 3건에 약 20~23초의 로컬 낭비가 관측되었다. 위 재검색 생략 조건을 추가하고 영향받는 5개 검사만 재검증했다. 최종 소스/해시는 `deliverables`의 ZIP이다. 앞선 `packages` 폴더는 중간 점검본이며 비교 제출에 사용하지 않는다. Windows 로컬 시간은 서버 진료 시간의 예측값이 아니다.

최종 6개 검색 조건에서 V1/V4의 추가 검색은 0회였다. 지침 병용 V1의 로컬 컨텍스트 구성은 약 17.5~19.3초였으며 기존 측정은 약 15.7~18.3초였다. 실행 환경·캐시·동시 작업 영향이 있어 속도 개선 수치로 해석하지 않는다. 관찰 창 자체는 v3.5와 같으므로 오래된 관찰이 기존 창에서 생략되는 한계도 그대로다.

**검증 결과:** 기존 회귀 66개 + 신규 전략 검사 11개 = 고유 77개 PASS. 전체 회귀를 후보마다 반복하지 않았다. 최초 요청 UUID 비교 실패와 기존 fixture 출력 경로 차단은 테스트만 수정하고 해당 항목만 재검증했다. 비용 개선 뒤에는 영향받는 RAG 검사와 검색 투영만 재검증했고, 크기 제한 검사는 실제 추가 경로를 거치도록 fixture를 확인했다. 20개 기존 자료의 해시 일치, 10개 사례×5후보의 원문·ID·RECORD 투영 보존을 확인했다. 자동 검사 내역과 임상 REVIEW는 `validation_summary.json`, ZIP별 설정·크기·SHA와 실제 진입점 mock 결과는 `candidate_manifest.json`에 고정한다.

**재사용 명령** — 이 worktree에서 기존 Python 3.12 사용, 매번 새 출력 경로 지정:

```powershell
$py = '../nova_rag_dev_20261015/doctor_agent_v2/validation/python312/python.exe'
& $py -X utf8 -B -I scripts/check_batch.py --output ../NEW_RUN/checks
& $py -X utf8 -B -I scripts/check_batch.py --retrieval-only --output ../NEW_RUN/retrieval
& $py -X utf8 -B -I ../nova-medical-agent-harness/scripts/dev_harness.py review --output ../NEW_RUN/review
& $py -X utf8 -B -I scripts/compare_batch.py ../NEW_RUN/comparison
& $py -X utf8 -B -I scripts/package_batch.py --output ../NEW_RUN/packages
```

실제 API·새 진료 세션·웹사이트 샘플검증·공식 제출·Docker/GCP·main 병합을 실행하지 않았다. 다음 웹사이트 비교는 사용자가 직접 수행한다. 실제 점수·안전 유지·실행 시간 개선은 보장하지 않는다.

**고정 ZIP 목록** — 공통 기준 `81714d340207a8e5ca9886dd2129cbd6b9cc61f2`. V0 변경 파일 없음, V1~V4 앱 변경 파일은 위 3개다. 모두 root `run.py`/`requirements.txt`, 압축 무결성, 파일 해시 및 추출 ZIP 진입점 mock PASS.

| 후보 / 실제 ZIP 경로 | 활성 기능 | 바이트 | SHA-256 |
|---|---|---:|---|
| [V0_baseline](<C:/Users/hjlee/OneDrive/문서/ChatGPT/의료 ai agent/nova_v35_simple_20261016/deliverables/nova_doctor_bm25_candidate_v3_5_simple_20261016.zip>) | v3.5 원본 | 44,989,264 | `31648ae7be3285c08f1103b9e7c741ba1b9af5e32f757b54cb91aebb2ea5faf7` |
| [V1_clinical_rag](<C:/Users/hjlee/OneDrive/문서/ChatGPT/의료 ai agent/nova_batch_clinical_experiments_20261021/deliverables/nova_doctor_bm25_candidate_V1_clinical_rag_20261021.zip>) | rag | 44,993,255 | `cf1aa5346b54e6c521c2c5186ba8f29f4d809940046bf3e2b4a03400d30d5103` |
| [V2_clinical_interview](<C:/Users/hjlee/OneDrive/문서/ChatGPT/의료 ai agent/nova_batch_clinical_experiments_20261021/deliverables/nova_doctor_bm25_candidate_V2_clinical_interview_20261021.zip>) | interview | 44,993,255 | `3d1dd8bb01ddd723b6ae31723db67633465ec566422a0184b96689c24daf14a7` |
| [V3_communication](<C:/Users/hjlee/OneDrive/문서/ChatGPT/의료 ai agent/nova_batch_clinical_experiments_20261021/deliverables/nova_doctor_bm25_candidate_V3_communication_20261021.zip>) | communication | 44,993,255 | `d748d88b1e9efb6e77508d929f4ac79fe3543d04f18d66e9718f8078aa4230ee` |
| [V4_integrated](<C:/Users/hjlee/OneDrive/문서/ChatGPT/의료 ai agent/nova_batch_clinical_experiments_20261021/deliverables/nova_doctor_bm25_candidate_V4_integrated_20261021.zip>) | rag, interview, communication | 44,993,255 | `b608b2ee87a28dd9d99d251f5815f0d46d4cbef99a5b64f1ef102645d4659d4f` |
