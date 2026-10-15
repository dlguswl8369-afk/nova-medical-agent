# NOVA v3.2 — RAG 구축·통합 검토 인계

## 1. 실행 방법과 환경변수

Python **3.12** 사용(기존 Linux 검증: 3.12.15). 런타임은 표준 라이브러리와 포함된 `app/nova_sdk.py`를 사용하며 `app/requirements.txt`에 추가 패키지는 없다. 인덱스·근거·정책 파일은 `app/` 아래 상대 경로를 유지한다.

- 오프라인 RAG: `cd app` 후 아래 Python 예시 사용. 키·네트워크 불필요. 선택 변수 `NOVA_RAG_INDEX`는 인덱스 경로를 재정의한다.
- Doctor 진입점: 승인된 NOVA 세션 환경에서 `cd app` → `python -B run.py`. 필수 변수 **NOVA_API_BASE**, **NOVA_RUN_TOKEN**, 선택 변수 **NOVA_SESSION_ID**. 이 명령은 실제 통신을 하므로 세션·실행 승인을 갖춘 후 사용한다. 비밀값은 포함하지 않았다.
- 기존 테스트 실행법(후속 작업용): 패키지 루트에서 `python -B -I scripts/run_v3_tests.py`. 이번 포장 작업에서는 실행하지 않았다. 테스트가 import하는 `scripts/public_samples.py`는 원본 그대로 포함했으나 직접 실행 대상이 아니다. 해당 개발용 도구의 `NOVA_DEV_KEY` 값·인증파일·실제 샘플 원장은 제외했다. `tests/sample_ledger_fixture.py`는 임시 합성 fixture를 만드는 테스트 코드다.

## 2. RAG 검색·근거 전달 연결 지점과 입출력

| 실제 위치 | 입력 → 출력 |
|---|---|
| `app/nova_agent/loop.py:prepare()` | 인자 없음 → `State(index, config, report)`; 기본 `app/indexes/bm25_ko.json.gz` 로드 |
| `app/nova_agent/context.py:query_from_facts()` | 관찰 dict 목록 → 관찰을 연결한 검색 문자열 |
| `app/nova_retrieval/index.py:BM25Index.search()` | 문자열, `top_k=5` → 순위·점수·본문·출처를 포함한 dict 목록 |
| `app/nova_agent/context.py:reference_packet()` | index, query, `max_chars=12000`, `top_k=5` → 정책·길이 조건을 통과한 완결 근거 목록; 조건을 만족하지 못하면 `[]` 가능 |
| `app/nova_agent/loop.py:Run.context()` → `Run.doctor()` | 관찰/근거 분리 JSON → SDK `Client.chat()` 호출; 진료 외부 연결은 `consult(client, state)` |

```python
# app/에서 사용하는 연결 예시. 이번 인계 중 실행하지 않음.
from nova_agent import prepare
from nova_agent.context import query_from_facts, reference_packet
state = prepare()
facts = [{"id": "F0", "kind": "opening", "text": "발열과 복통", "question": None}]
query = query_from_facts(facts)  # "[F0] 시작 정보: 발열과 복통"
hits = state.index.search(query, top_k=5)
refs = reference_packet(state.index, query, top_k=5)
```

출력 형태 예시(실측 검색 결과 아님; `<...>`는 값 자리): `hits` 항목은 `{"rank": 1, "score": "<float>", "chunk_id": "<id>", "text": "<본문>", "source_page": "<쪽>", "evidence_ids": ["<id>"]}`. `refs` 항목은 `{"document_id": "<id>", "text": "<완결 원문 단위>", "source_sha256": "<원본 해시>", "unit_location": {"parent_id": "<id>", "start": 0, "end": "<int>", "field": "text"}, "not_current_patient_facts": true, "external_submission_status": "UNCONFIRMED"}` 등의 실제 필드를 갖는다. `Run.context()`는 이를 `reference_evidence`에 넣고 `current_patient_observations`와 구분한다. 검색 근거를 현재 환자 사실로 합치지 않는다.

## 3. 완료 사항

검색 자료 6개 **774항목**, BM25 RAG와 Doctor 연결 완료. 기존 GCP Linux 검증에서 실제 `run.py`·SDK 진입점의 합성 진료 **3/3**, 테스트 **145/145** 통과(실제 API 호출 0). [검증 요약](reports/linux_validation/SUMMARY.md)에 실행 제한과 원시 결과 링크를 보존했다. `app/` 22개 파일은 보존 후보 ZIP과 바이트가 같으며 후보 SHA-256은 `831560900bd759a0af4260ec9af0b25dede46f98f2a3d293315e061464aceaf8`이다.

## 4. 한계

**calibration Recall@5 1/6**: 동일 인덱스의 과거 검색 평가이며 이번 새 평가가 아니다([기존 결과](reports/calibration_retrieval_existing.json)). **진단·기록 임상 품질 미평가**, 비공개 대회 서버와의 동일성 미검증. 합성 성공은 임상 정확도를 뜻하지 않는다. **외부 제출 이용 조건 미확정**([자료 이용 조건 보고서](rights/SOURCE_RIGHTS_REVIEW.md)). [고지문 수정안](rights/ASSET_NOTICE_PROPOSED.md)은 **미적용**이며 `app/ASSET_NOTICE.md`는 기존 그대로다. 이 패키지는 개발·통합 검토용이고 외부 제출·공개 허락을 확정하지 않는다.

## 5. 후속 담당자가 결정할 사항

1. 기존 코드와의 통합 방식: `prepare`/`consult` 전체 연결 또는 검색·근거 전달 함수를 분리해 연결할지 결정.
2. 추가 사례 평가: 검색 누락 및 진단·기록 임상 품질의 평가 사례와 기준 결정.
3. 최종 제출 준비: 자료별 이용 조건 확정, 고지 수정안 적용 여부와 통합 후 검증·제출 절차 결정.
