# H1–H4 고강도 임상 전략 실험 · 2026-10-22

v3.5 `81714d340207a8e5ca9886dd2129cbd6b9cc61f2`에서 직접 분기했다. 기존 v3.3–v3.8 및 V1–V4 코드·후보·원장은 보존했다. **모든 후보의 임상 성능은 NOT_EVALUATED**이며, 80점 달성이나 안전 점수 유지를 보장하지 않는다. 과거 점수는 사용자 제공 집계이며 이번 구조의 효과나 과거 감점 원인을 입증하지 않는다.

## 네 실행 경로

| 후보 | 실제 실행 차이 | 보조 Doctor 호출 최대 | 주요 위험 |
|---|---|---:|---|
| H1 Clinical Planner | 첫 성공 행동 이후 최신 답변을 읽은 ACTION이 계획 필요성을 표시하면 잠정 계획 호출. 다음 행동 제안은 기존 파서로 검증해 실행하며, 계획 수정은 후속 ACTION에서 가능 | 1 | 계획 신호 누락으로 미활성화, 가설 고착·낡은 계획, 입력·지연 증가 |
| H2 Focused Examination | 같은 ACTION 호출에서 문진과 진찰의 결정 가치를 비교. 유효한 관찰 ID·판단 목적을 붙인 EXAM 대안이 선택되면 실제 진찰로 실행. SDK 거부 사유를 다음 행동에 제공하며 동일 거부 문구 반복 방지 | 0 | ID가 존재해도 임상적 적절성은 보장되지 않음. 불필요하거나 거부되는 진찰로 턴 소모 가능 |
| H3 Pre-DONE Audit | 첫 DONE에 한해 별도 호출이 원문 관찰·실제 설명 이력을 검토. ASK/EXAM/EXPLAIN 하나 또는 DONE. 충분함·잘못된 출력·시간/예산 부족·일시 실패 시 기존 DONE 허용 | 1 | 같은 모델의 누락·과잉 확인, 실패 시 누락을 그대로 남길 가능성 |
| H4 Integrated Clinician | H1+H2+H3. 종료 검토에는 계획 텍스트를 전달하지 않아 원문과 전달 이력을 다시 검토 | 2 | 결합 효과 불확실, 지연·비용·불필요한 추가 행동 위험. 종료 검토의 조건부 high도 함께 실험하므로 순수한 기능 합산 비교가 아님 |

모든 후보는 `experiment_config.py`에 H1/H2/H3/H4가 고정되어 별도 설정 없이 실행된다. 저장소 기본값은 BASELINE이다. 최초 행동 앞에는 계획 호출을 넣지 않으며, 현재 ACTION의 `urgent:true`는 계획·진찰 대안 전환보다 우선한다. 위험 인식 자체는 모델의 판단이며 코드가 임상적으로 검증하지 않는다. 선택적 메타데이터가 없거나 잘못된 진찰 대안이면 원래 유효 행동을 유지한다. 필수 문진표·EXAM 횟수·설명 횟수·review JSON·DONE 강제 차단은 없다.

## 변경과 보호

- `app/nova_agent/loop.py`: 세션별 계획·첫 DONE 검토·진찰 대안 연결, 보조 호출의 기존 예산 예약·정산, 거부 사유 전달. 계획과 실패 이력은 ACTION의 별도 필드이며 관찰·검색 질의·RECORD에 넣지 않는다.
- `app/nova_agent/clinical_strategy.py`: 기능 조합, 계획/검토 프롬프트, 선택적 EXAM 대안의 형식·관찰 ID 검사. 임상적 필요성을 정규식으로 판정하지 않는다. 모든 후보의 실행 STEP에서 “검사 계획은 최종 P에만” 충돌을 해소한다.
- `app/nova_agent/experiment_config.py`: ZIP별 전략 고정.
- `scripts/check_high_intensity.py`, `tests/test_high_intensity_policy.py`: 기존 하네스의 보호 심볼 중 **Run.doctor의 명시된 9개 변환만** 별도 정책으로 허용한다. MODEL·Config·prepare·SDK·원장·기록·RAG는 원래 보호를 유지한다. 하네스 원본은 수정하지 않았다.
- `tests/test_high_intensity.py`, `scripts/package_high_intensity.py`, `scripts/review_high_intensity.py`: 새 경로 회귀, 압축 해제한 실제 진입점 mock, 기존 사례의 읽기 전용 컨텍스트 대조.

`prompts.py` 파일과 RECORD 문자열, 원문 S/O 조립, 실제 SDK 성공 뒤에만 관찰·설명을 저장하는 경로, RAG 자료·선택·예산, 기존 SDK는 그대로다. 새로운 모델 전송 경로를 만들지 않고 기존 `Run.doctor`만 사용한다. 기존 하네스의 네트워크·프로세스·출력 외 쓰기 차단을 그대로 재사용한다. 이는 시험 프로세스의 기술적 차단이며 모든 사용자 명령을 운영체제 전체에서 막는 보안 장치는 아니다.

## 실행 한도와 비용

[공식 규칙](https://nova.snubhai.org/rules/)의 50턴·Doctor 200회·30분·SAY/EXAM NFC 30자·예선 TEST 금지·ZIP 50,000,000바이트 제한을 확인했다. 이번 후보는 비교 변수를 줄이기 위해 **기존 30턴/80회, 입력 500,000·출력 100,000, 최종 기록 시간 여유 300초**를 유지했다. 40턴 변형은 만들지 않았다.

| 호출 | 모델 / 추론 / 출력 상한 | 추가 지연 상한 설정 |
|---|---|---|
| 기존 ACTION | openai/gpt-6-luna / medium / 2048 | 기존 설정 유지 |
| 기존 RECORD | 동일 / medium / 4096 | 기존 설정 및 최대 3회 기록 예약 유지 |
| H1/H4 계획 | 동일 / medium / 3072 | 120초, 재시도 없음 |
| H3 종료 검토 | 동일 / medium / 3072 | 120초, 재시도 없음 |
| H4 종료 검토 | 남은 시간이 600초 초과이면 high / 4096, 그 외 medium / 3072 | high 180초 또는 medium 120초, 재시도 없음 |

보조 호출은 남은 시간 480초 이하 또는 행동 여유 부족이면 생략하며, 최종 기록 예산을 예약하지 못해도 생략한다. 출력 상한은 [공식 문서](https://nova.snubhai.org/docs/)에 따라 추론 토큰도 포함하므로 high에서 빈 출력·잘린 JSON이 나올 위험이 남는다. H1/H3의 보조 출력 예약 최대는 각각 3072, H2는 0, H4는 7168이다. 실제 사용량은 미측정이다. 계획은 최대 1600자이며 이후 ACTION 입력에 반복 포함되므로 비용 증가 요인이다.

추가 호출 1/2회는 **보조 호출 상한**이다. 그 제안으로 진료가 이어지면 일반 ACTION 호출·턴도 늘 수 있으나 전체 30턴/80회 및 기록 예약 한도를 공유한다. 타임아웃은 클라이언트 설정이며 실제 전체 처리 시간 보장은 아니다. [공식 평가](https://nova.snubhai.org/evaluation/)는 실제 행동과 SOAP를 함께 보고 효율에 턴·모델 비용을 반영하므로, 더 많은 확인이 곧 더 높은 점수를 뜻하지 않는다.

## 검증 결과와 한계

공통 회귀 55개 + 새 실행 경로 15개 + 정책 회귀 7개, **77/77 PASS**. 공통 묶음은 한 번 실행했다. 계획과 실제 수행 분리, 최신 답변 이후 계획 허용, 긴급 행동 유지, 진찰 선택·거부 복구, 부분 답변 원문, 실제 설명과 P 분리, 첫 DONE 검토/충분 시 종료/실패 시 복귀, 시간·호출·추론 출력 예약 및 최종 DIAGNOSE 경로를 확인했다. SDK가 세션을 닫거나 네트워크가 단절된 상황에서 DIAGNOSE 접수까지 보장하지 않는다.

압축 해제 진입점 검증, 사례 대조 및 ZIP 식별자는 아래 산출물 표와 `RESULTS.json`에 고정한다. mock은 행동을 미리 지정하며 임상적 질문·진찰·설명 선택 능력의 증거가 아니다. 기존 10개 사례의 임상적 충분성은 **REVIEW**, 신규 모델 행동·실제 토큰/지연·점수는 **NOT_EVALUATED**다. 과거 로그는 v3.2/v3.3이고 이번 실행 결과가 아니다. [사례별 근거와 한계](CLINICAL_REVIEW.md)를 참조한다.

출처 해시 20개와 기존 10개 사례 × BASELINE/H1/H2/H3/H4의 **50개 컨텍스트 투영 PASS**. 이번 자료에서는 선택 누락 0개이고 관찰·RECORD 입력이 같았다. 이 대조는 검색을 재실행하지 않는 빈 인덱스 조건이며 실제 RAG 코드는 별도의 파일 동일성 검사로 보호했다. 계획 없는 ACTION의 UTF-8 입력 증가는 H1 +743, H2 +837, H3 +288, H4 +1292바이트였다. 이는 측정 토큰 수가 아니며 생성 계획이 있으면 그 입력량이 추가된다.

기존 `fact_chars` 제한 때문에 긴 진료의 중요한 과거 관찰이 ACTION/검토에 보이지 않는 위험은 남아 있다. 새 계획이 사실처럼 추론에 영향을 주는 위험, 부분 답변을 A에서 과해석하는 위험, 안전 신호 인식·임상적 EXAM 필요성·실제 설명의 적절성은 모델 및 사람 검토가 필요하다. 이번 작업에서 실제 API·새 진료·웹사이트 평가·제출·Docker/GCP·main 병합은 실행하지 않았다.

## 재현 명령

새 출력 경로를 사용한다. Python 3.12로 저장소 루트에서 실행하며 기존 출력은 덮어쓰지 않는다.

```powershell
$py = '../nova_rag_dev_20261015/doctor_agent_v2/validation/python312/python.exe'
& $py -X utf8 -B -I scripts/check_high_intensity.py --output ../nova_high_intensity_experiments_20261022/checks-new
& $py -X utf8 -B -I scripts/review_high_intensity.py --output ../nova_high_intensity_experiments_20261022/context-review-new
& $py -X utf8 -B -I scripts/package_high_intensity.py --output ../nova_high_intensity_experiments_20261022/deliverables-new --validation ../nova_high_intensity_experiments_20261022/checks-new/validation.json
```

브랜치: `codex/nova-high-intensity-clinical-experiments`. 이 보고서를 포함하는 커밋이 실행 코드·정책·테스트의 버전이다. ZIP·인덱스·원문·원장은 새로 Git에 추가하지 않는다.

## 고정 산출물

| 후보 ZIP | 바이트 | SHA-256 | 진입점 / 보조 호출 |
|---|---:|---|---|
| [nova_doctor_bm25_candidate_H1_clinical_planner_20261022.zip](<C:/Users/hjlee/OneDrive/문서/ChatGPT/의료 ai agent/nova_high_intensity_experiments_20261022/deliverables/nova_doctor_bm25_candidate_H1_clinical_planner_20261022.zip>) | 44,993,741 | `412aec863000693abaadb34f77e07014a65bda9ba47aa3eaaf2ac99ade131ef6` | PASS / 최대 1회 |
| [nova_doctor_bm25_candidate_H2_focused_examination_20261022.zip](<C:/Users/hjlee/OneDrive/문서/ChatGPT/의료 ai agent/nova_high_intensity_experiments_20261022/deliverables/nova_doctor_bm25_candidate_H2_focused_examination_20261022.zip>) | 44,993,741 | `cc0044d33bc3c0a21069497381b8733671c86373b88bc941a2c083e01ef367d7` | PASS / 최대 0회 |
| [nova_doctor_bm25_candidate_H3_pre_done_audit_20261022.zip](<C:/Users/hjlee/OneDrive/문서/ChatGPT/의료 ai agent/nova_high_intensity_experiments_20261022/deliverables/nova_doctor_bm25_candidate_H3_pre_done_audit_20261022.zip>) | 44,993,741 | `181bbb2c9b7953ab1db3c442eac40addec80f94f3b3e62cee0b0e2e66cf09f5f` | PASS / 최대 1회 |
| [nova_doctor_bm25_candidate_H4_integrated_clinician_20261022.zip](<C:/Users/hjlee/OneDrive/문서/ChatGPT/의료 ai agent/nova_high_intensity_experiments_20261022/deliverables/nova_doctor_bm25_candidate_H4_integrated_clinician_20261022.zip>) | 44,993,741 | `2d993cd6a29514a3243fa4e180f0313954e3aac6b1cb630c7de5fa4003f302fe` | PASS / 최대 2회 |

네 ZIP 모두 26개 파일, 루트 `run.py`·`requirements.txt`, CRC·구문·크기·압축 해제 후 코드 해시 검사 PASS. 실제 `run.py` → prepare → consult → SDK(mock) → DIAGNOSE 경로도 4/4 PASS다. 보조 호출 수는 H1/H2/H3/H4에서 각각 1/0/1/2회로 구분됐다. 이 숫자는 지정된 mock 시나리오 결과이며 실제 환자당 호출 수의 예측이 아니다.

전체 로컬 근거: `nova_high_intensity_experiments_20261022/checks/validation.json`, `clinical_review/review.json`, `context_review/review.json`, `deliverables/manifest.json`. 경로·근거 해시·후보별 실행 설정은 [RESULTS.json](RESULTS.json)에 고정했다.
