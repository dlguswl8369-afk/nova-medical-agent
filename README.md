# NOVA 의료 에이전트 — BM25 RAG

**이 브랜치는 v3.3 운영진 지침 RAG·개발/평가 확장을 포함한다.** [확장 사용법](docs/EXTENSION_V3_3.md), [공식 계약 대조](docs/OFFICIAL_CONTRACT.md), `reports/extension_20261015/`의 새 결과를 참고한다. 아래 v3.2 인계 설명은 기존 기준본의 기록이다.

NOVA 의료 에이전트의 검색 근거 전달과 Doctor 연결 코드를 공동 개발·통합 검토하기 위한 비공개 저장소다. 6개 자료를 **774개 검색 항목**으로 구성한 한국어 BM25 RAG, 공식 NOVA SDK 연결, 진료 루프, 예산·오류 복구·최종 기록 처리와 기존 합성 테스트를 포함한다.

## 처리 흐름

환자 증상·문진 답변·실제 진찰 결과 → 관찰 기반 검색 질의 → BM25 검색 → 출처·원본 해시·근거 위치를 포함한 근거 패킷 → 공식 NOVA SDK → Doctor 모델 → 진료 루프 및 최종 기록·진단.

관찰 사실과 참고 근거는 별도 필드로 전달한다. 검색 자료를 현재 환자의 사실로 합치지 않는다. 현재 코드의 Doctor 모델은 `openai/gpt-6-luna`다. 실제 연결 함수와 입출력은 [HANDOFF.md](HANDOFF.md)를 참고한다.

## 환경과 설치

**Python 3.12** 기준이며 기존 Linux 검증은 Python 3.12.15에서 수행했다. 앱과 SDK는 표준 라이브러리를 사용한다. `app/requirements.txt`에는 현재 추가 설치 패키지가 없다. 아래 `python` 명령은 Python 3.12 실행 파일을 가리켜야 한다.

```text
nova-medical-agent/       ← 저장소 루트
  app/                   ← run.py, SDK, RAG·Doctor 코드, indexes/, assets/
  scripts/               ← 기존 테스트 실행기와 테스트 의존 도구
  tests/                 ← 기존 합성 테스트·fixture 코드
  reports/               ← 기존 Linux 검증·calibration 결과
  rights/                ← 이용 조건 보고서·미적용 고지문 수정안
  HANDOFF.md
```

필요하면 저장소 루트에서 `python -m venv .venv`로 가상환경을 만든 뒤 해당 환경의 Python을 사용한다. `app/indexes/`와 `app/assets/`의 상대 경로를 유지한다.

## 키 없는 오프라인 검색

터미널에서 저장소 루트 기준 `cd app` 후 `python -B`를 실행하고 다음 Python 코드를 입력한다. 키·API·네트워크 없이 로컬 인덱스를 읽는다.

```python
from nova_agent import prepare
from nova_agent.context import query_from_facts, reference_packet

state = prepare()
facts = [{"id": "F0", "kind": "opening", "text": "발열과 복통", "question": None}]
query = query_from_facts(facts)
hits = state.index.search(query, top_k=5)
refs = reference_packet(state.index, query, top_k=5)
for hit in hits:
    print(hit["rank"], hit["title"], hit.get("source_page"), hit.get("relative_path"), hit.get("evidence_ids"))
print(refs)
```

이는 사용 예시이며 이번 GitHub 등록 중 실행하지 않았다. `reference_packet()`은 정책과 완결 근거 단위·길이 제한을 적용하므로 검색 결과와 수량이 다르거나 빈 목록일 수 있다. `NOVA_RAG_INDEX`는 기본 인덱스 경로를 바꾸는 선택 환경변수다.

## 실제 Doctor 실행

승인된 NOVA 세션에서 **NOVA_API_BASE**, **NOVA_RUN_TOKEN**을 환경변수로 제공한다. **NOVA_SESSION_ID**는 선택 변수다. 비밀값을 코드·설정 파일·Git에 저장하지 않는다.

저장소 루트에서 다음을 실행한다.

```text
cd app
python -B run.py
```

이 명령은 공식 SDK를 통해 **실제 API 통신을 발생시킨다**. 세션 및 실행 권한을 갖춘 환경에서만 사용한다. 개발용 `scripts/public_samples.py`는 기존 테스트가 import하는 의존 코드로 보존했으며, 이 안내의 실행 대상이 아니다. 해당 도구의 `NOVA_DEV_KEY` 값이나 실제 공개 샘플 원장은 포함하지 않았다.

## 기존 검증과 한계

- 기존 GCP Linux 검증: 합성 진료 **3/3**, 테스트 **145/145** 통과. 실제 NOVA API 호출 0.
- 컨테이너 CPU 2개, RAM 8 GiB, 추가 스왑 0, 네트워크 차단, 읽기 전용 루트, UID 65532 조건에서 검증했다. [기존 Linux 검증 요약](reports/linux_validation/SUMMARY.md)과 원시 JSON을 보존했다.
- 위 결과는 **기존 검증 기록**이다. 이번 GitHub 등록 중 테스트·API·샘플 생성·VM 실행을 재수행하지 않았다. 향후 기존 테스트를 실행할 때는 저장소 루트에서 `python -B -I scripts/run_v3_tests.py`를 사용한다.
- 동일 인덱스의 과거 calibration **Recall@5 1/6**으로 검색 누락이 남아 있다. 진단 정확도와 기록의 임상 품질은 평가하지 않았으며, 비공개 대회 서버와의 동일성도 확인하지 않았다.

## 자료 이용 조건

자료의 **외부 제출·공개 이용 조건은 미확정**이다. 비공개 저장소를 만들었다고 이 문제가 해결되는 것은 아니다. [자료 이용 조건 보고서](rights/SOURCE_RIGHTS_REVIEW.md)와 [자료별 근거표](rights/SOURCE_EVIDENCE_MATRIX.md)를 확인해야 한다.

`app/ASSET_NOTICE.md`는 원본 그대로다. [ASSET_NOTICE_PROPOSED.md](rights/ASSET_NOTICE_PROPOSED.md)는 **미적용 수정안**이며, 문의 초안도 전송하지 않았다. 저장소 전체에 MIT 등 공개 라이선스를 부여하지 않는다.

## 기준 패키지와 보존 기록

기준 패키지명: **NOVA_v3_2_RAG_구축_통합검토_20261015.zip**.

검증한 실제 SHA-256:

```text
1442d35f29615fc6e256ffeeb124978a1211be339da064ec55a338cfa12690df
```

요청에 기재된 `cd5e4f2f016d10880c13e56017d1667b0d8733f36d4fde2f8dacbfb45c287071`은 내부 이름 수정 전 ZIP의 해시다. 앞선 이름 정리에서 ZIP 내부 포장 폴더명, HANDOFF.md의 사람 이름 및 파생 해시 기록도 갱신되어 위 해시로 바뀌었다. 바탕화면으로 이동된 실제 ZIP이 앞서 기록한 수정본 해시와 일치하며 내부 해시 목록 105개도 모두 대조했다. 다른 패키지로 대체하지 않았다.

초기 커밋은 포장 폴더만 제거하고 106개 원본 파일을 보존했다. 이후 이 브랜치의 v3.3 확장에서 앱 연결 코드·검색 인덱스·평가 도구를 추가/변경했다. 기존 v3.2 후보와 보고서 원본은 별도 프로젝트 경로에 보존한다. 키·인증파일·실제 샘플 원장·환자 세션 원문 로그는 기준 패키지에 없으며, 포함된 검증 시나리오와 원장 fixture 코드는 합성 데이터다. `.gitignore`는 향후 비밀정보·가상환경·캐시·실행 산출물·중복 압축파일의 유입을 방지한다.

`PACKAGE_MANIFEST.json`과 `SHA256SUMS.txt`는 **원래 인계 패키지의 기록**으로 수정하지 않았다. 새 README·.gitignore 및 Git 이력을 포함하는 현재 저장소 전체의 manifest가 아니며, 원래 로컬·컨테이너 경로와 당시 보존 확인은 역사적 기록이다. 이 브랜치의 새 코드/인덱스는 당시 manifest와 다르며, 원래 인계 manifest를 현재 확장 버전의 해시 목록으로 사용하지 않는다.
