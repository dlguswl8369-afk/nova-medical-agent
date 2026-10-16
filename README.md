# NOVA 의료 에이전트 — BM25 RAG

**현재 브랜치는 v3.5 simple 후보다.** v3.3의 단순 행동·종료 흐름을 복원하고 검색 캐시·실제 설명 확인·관찰 원문 보존·길이 재생성은 유지했다. [최신 변경·이번 197개 오프라인 검증·후보 정보](reports/v35_simple_20261016/REPORT.md)를 확인한다. 실제 진료 품질·안전 점수 개선과 새 후보 Linux 동작은 미확인이다. [이전 v3.4 후속 결과](reports/v34_followup_20261016/REPORT.md)와 아래 과거 검증 기록은 현재 후보의 통과 근거로 재사용하지 않는다.

**기준 버전 v3.3은 v3.2에 운영진 지침 검색과 개발·평가 흐름을 추가했다.** [확장 사용법](docs/EXTENSION_V3_3.md), [공식 계약 대조](docs/OFFICIAL_CONTRACT.md), [v3.3 검증 결과](reports/extension_20261015/REPORT.md), [실제 공개 샘플 비교](reports/extension_20261015/PUBLIC_COMPARISON.md)를 참고한다. 아래 v3.2 검증·인계 패키지 기록은 별도로 구분한다.

NOVA 의료 에이전트의 검색 근거 전달과 Doctor 연결 코드를 공동 개발·통합 검토하기 위한 비공개 저장소다. 기존 6개 자료의 **774개 검색 항목**과 운영진 제공 **15,904문서(한국어 1,506·영어 14,398)**를 선택적으로 검색한다. 공식 NOVA SDK 연결, 진료 루프, 예산·오류 복구·최종 기록 처리, 공식 `develop.py`용 개발 어댑터와 평가 도구를 포함한다.

## v3.3 검색 소스와 데이터 준비

운영진 원문 전체를 Git이나 제출 코드 ZIP에 넣지 않는다. 대회에서는 `NOVA_GUIDELINES_DIR`이 가리키는 `/opt/nova/guidelines`에서 원문을 읽는다. 개발 환경에서는 공식 자료를 저장소 밖에 별도로 준비하고 `catalog.csv`가 있는 폴더를 지정한다. [자료 준비 절차](docs/EXTENSION_V3_3.md#공식-자료를-별도로-준비하기)를 따른다.

기존 추적 파일 `app/indexes/guidelines.sqlite`에는 검색용 메타데이터·원문 해시·해시된 검색어/빈도 목록을 저장하며 본문 전체는 저장하지 않는다. 실행 중 다운로드하거나 영구 캐시를 쓰지 않는다.

| `NOVA_RAG_SOURCES` | 동작 |
|---|---|
| `auto` (기본) | 지정 지침 폴더가 존재하면 두 자료군 사용, 없으면 기존 774항목만 사용 |
| `legacy` | 기존 774항목만 검색 |
| `guidelines` | 운영진 15,904문서만 검색 |
| `legacy,guidelines` | 두 자료군을 함께 검색 |
| `none` | 검색 근거 없이 실행 |

`NOVA_GUIDELINES_DIR` 미설정 시 기본 경로는 `/opt/nova/guidelines`다. `auto`는 폴더 존재 여부로 선택하므로 빈 폴더를 만들면 기존 검색으로 자동 복구하지 않는다. 지침 검색을 선택한 상태에서 catalog·인덱스가 없거나 필요한 원문 해시가 다르면 실패한다. 개발용 인덱스를 별도 지정하려면 `NOVA_GUIDELINES_INDEX`를 사용한다.

## v3.3 검증·평가 기록

아래는 **2026-10-15에 실행한 v3.3 기록**이다. 이후 v3.3 문서 정리에서는 재실행하지 않았다. 이번 v3.4 작업에서는 별도 오프라인 검증만 실행했으며 결과는 상단 v3.4 보고서에 구분했다. 기존 버전 결과를 v3.4 통과 결과로 재사용하지 않는다.

- 새 코드의 기존 회귀 **145/145**, 추가 검색·정보 분리 **13/13**: Windows와 새 Linux 검증에서 통과.
- 원장·평가 도구 안전성 **9/9**: Windows 통과. 새 후보의 실제 `run.py`·SDK 합성 진료 **3/3**: Linux 통과.
- Linux 제한: CPU 2·RAM 8GiB·추가 스왑 0·`network=none`·읽기 전용 루트·UID 65532. 실제 Docker 설정과 내부 cgroup 등을 대조했다.
- 공식 `develop.py` 로더·`prepare()` 연결 확인. AgentClinic·DDXPlus·ACI-Bench 각 5개, **15/15** 오프라인 파싱·입력 분리 점검. 로컬 모델 진료와 전체 벤치마크 모델 평가는 미실행.

실제 공개 샘플은 각 사례·버전을 한 번씩, 새 세션 6개로 비교했다. 서버는 **6/6 완료**, 앱 정상 종료는 **4/6**이다. 서버의 기록 접수 완료를 진료 품질 통과로 해석하지 않는다.

| 사례 | v3.2 | v3.3 |
|---|---|---|
| C01 | 행동 형식 오류 종료 후 기록 제출 | 정상 종료 |
| C10 | 정상 종료 | 행동 형식 오류 종료 후 기록 제출 |
| C03 | 정상 종료 | 정상 종료 |

행동 문장의 30자 상한 위반으로 재시도 한도를 소진한 문제가 남아 있다. C10 확장본의 최종 제출 후 상태 조회 시간 초과는 보존된 서버 완료 응답으로 정리했으며 중복 세션을 만들지 않았다. [비교 결과](reports/extension_20261015/PUBLIC_COMPARISON.md)에 호출 수·토큰·시간을 보존했다.

세션 밖 자체 검토 3회는 세부 채점 기준 부족으로 숫자 점수 대신 정성 비교를 반환했다. **마지막 검색 근거의 낮은 관련성, 일부 제목·서지 위주 근거, C03 확장본의 미답변 항목을 음성으로 기록한 문제**가 지적됐다. [정성 검토와 한계](reports/extension_20261015/SELF_REVIEW_NOTES.md)를 확인한다. 임상 품질이나 비용 개선은 입증되지 않았으며 실제 API 청구액도 미확인이다. 자료별 외부 제출·공개 이용 조건 역시 미확정이다.

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

## v3.2의 기존 검증과 한계 — 역사적 기록

- 기존 GCP Linux 검증: 합성 진료 **3/3**, 테스트 **145/145** 통과. 실제 NOVA API 호출 0.
- 컨테이너 CPU 2개, RAM 8 GiB, 추가 스왑 0, 네트워크 차단, 읽기 전용 루트, UID 65532 조건에서 검증했다. [기존 Linux 검증 요약](reports/linux_validation/SUMMARY.md)과 원시 JSON을 보존했다.
- 위 결과는 **기존 검증 기록**이다. 이번 GitHub 등록 중 테스트·API·샘플 생성·VM 실행을 재수행하지 않았다. 향후 기존 테스트를 실행할 때는 저장소 루트에서 `python -B -I scripts/run_v3_tests.py`를 사용한다.
- 동일 인덱스의 과거 calibration **Recall@5 1/6**으로 검색 누락이 남아 있다. 진단 정확도와 기록의 임상 품질은 평가하지 않았으며, 비공개 대회 서버와의 동일성도 확인하지 않았다.

## 자료 이용 조건

자료의 **외부 제출·공개 이용 조건은 미확정**이다. 비공개 저장소를 만들었다고 이 문제가 해결되는 것은 아니다. [자료 이용 조건 보고서](rights/SOURCE_RIGHTS_REVIEW.md)와 [자료별 근거표](rights/SOURCE_EVIDENCE_MATRIX.md)를 확인해야 한다.

`app/ASSET_NOTICE.md`는 원본 그대로다. [ASSET_NOTICE_PROPOSED.md](rights/ASSET_NOTICE_PROPOSED.md)는 **미적용 수정안**이며, 문의 초안도 전송하지 않았다. 저장소 전체에 MIT 등 공개 라이선스를 부여하지 않는다.

## v3.2 기준 패키지와 보존 기록

기준 패키지명: **NOVA_v3_2_RAG_구축_통합검토_20261015.zip**.

검증한 실제 SHA-256:

```text
1442d35f29615fc6e256ffeeb124978a1211be339da064ec55a338cfa12690df
```

요청에 기재된 `cd5e4f2f016d10880c13e56017d1667b0d8733f36d4fde2f8dacbfb45c287071`은 내부 이름 수정 전 ZIP의 해시다. 앞선 이름 정리에서 ZIP 내부 포장 폴더명, HANDOFF.md의 사람 이름 및 파생 해시 기록도 갱신되어 위 해시로 바뀌었다. 바탕화면으로 이동된 실제 ZIP이 앞서 기록한 수정본 해시와 일치하며 내부 해시 목록 105개도 모두 대조했다. 다른 패키지로 대체하지 않았다.

초기 커밋은 포장 폴더만 제거하고 106개 원본 파일을 보존했다. 이후 이 브랜치의 v3.3 확장에서 앱 연결 코드·검색 인덱스·평가 도구를 추가/변경했다. 기존 v3.2 후보와 보고서 원본은 별도 프로젝트 경로에 보존한다. 키·인증파일·실제 샘플 원장·환자 세션 원문 로그는 기준 패키지에 없으며, 포함된 검증 시나리오와 원장 fixture 코드는 합성 데이터다. `.gitignore`는 향후 비밀정보·가상환경·캐시·실행 산출물·중복 압축파일의 유입을 방지한다.

`PACKAGE_MANIFEST.json`과 `SHA256SUMS.txt`는 **원래 인계 패키지의 기록**으로 수정하지 않았다. 새 README·.gitignore 및 Git 이력을 포함하는 현재 저장소 전체의 manifest가 아니며, 원래 로컬·컨테이너 경로와 당시 보존 확인은 역사적 기록이다. 이 브랜치의 새 코드/인덱스는 당시 manifest와 다르며, 원래 인계 manifest를 현재 확장 버전의 해시 목록으로 사용하지 않는다.
