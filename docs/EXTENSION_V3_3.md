# v3.3 지침 RAG·개발·평가 사용법

v3.2 위에 추가한 개발 후보다. 기존 후보와 보고서는 보존하며, 이전 통과 결과를 새 버전 결과로 재사용하지 않는다. 공식 업로드·진행 중 채점 취소·재제출은 하지 않았다.

## 운영진 지침

catalog와 모든 문서 헤더를 대조했다. **15,904개(영어 14,398·한국어 1,506)**, 10개 문서 유형·16개 출처 폴더다. 집계·라이선스 분포는 `reports/extension_20261015/guidelines_build.json` 참조.

`app/nova_retrieval/guidelines.py`는 한국어 단어/bigram·영어 단어 BM25 검색을 제공한다. SQLite에는 검색어의 64bit BLAKE2b 해시와 postings/빈도, 문서 길이, 메타데이터, 원문 해시를 저장하며 **본문은 저장하지 않는다**. 검색 시 외부 원문 해시를 확인하고 완결 H2 구간(하위 제목·목록 포함) 또는 완결 본문을 읽는다. 제목·기관·연도·언어·URL·라이선스·상대 경로·문자 위치를 반환한다.

두 RAG를 순위별로 번갈아 합치고 정규화 URL·원본 해시·정규화 제목으로 중복 근거를 제외한다. 서로 다른 서지/URL의 의미상 중복까지 완전히 제거한다는 주장은 하지 않는다. 환자 관찰과 참고 근거 분리, 부정 표현 보존, 완결 근거 단위, **JSON 패킷 12,000자 제한**을 유지한다. 긴 근거를 잘라 넣지 않는다. BM25는 부정의 임상적 의미를 이해하지 않으며 자동 번역·교차언어 의미 검색도 추가하지 않았다.

| 환경변수 | 설정 |
|---|---|
| `NOVA_GUIDELINES_DIR` | catalog.csv가 있는 원문 폴더. 서버 `/opt/nova/guidelines`, 개발 시 로컬 폴더 지정 |
| `NOVA_GUIDELINES_INDEX` | 선택. 기본 `app/indexes/guidelines.sqlite` |
| `NOVA_RAG_SOURCES` | `legacy`, `guidelines`, `legacy,guidelines`, `none`, `auto` |
| `NOVA_RAG_INDEX` | 기존 774항목 인덱스 경로 |

기본 `auto`는 지침 폴더가 있으면 두 RAG, 없으면 기존 RAG를 사용한다. 지침을 명시했는데 경로·catalog·원문 해시가 맞지 않으면 실패한다. 런타임 다운로드·영구 캐시 쓰기는 없고 DB는 읽기 전용으로 연다.

Python 3.12, 저장소 루트에서 사전 생성:

```text
python -B -I scripts/build_guidelines_index.py --root /path/to/guidelines --output /path/to/new-guidelines.sqlite --report /path/to/build-report.json
```

기존 인덱스는 덮어쓰지 않는다. 생성 후 환경변수로 지정하거나 별도 배포 준비 과정에서 기본 위치에 둔다. 지침 원문 전체는 코드 ZIP/Git에 포함하지 않는다. 인덱스라는 이유로 이용 조건이 해결되는 것은 아니다.

## 공식 develop.py

키트 폴더에서 실행한다. C01·C10·C03을 각각 선택할 수 있다.

```text
python develop.py --list
python develop.py --case samples/C01 --agent /path/to/repository/dev/local_agent.py --out /private/local-results --quiet
```

환경변수는 `NOVA_LOCAL_DOCTOR_URL`, `NOVA_LOCAL_DOCTOR_MODEL`, `NOVA_LOCAL_DOCTOR_KEY`, `NOVA_LOCAL_SIM_URL`, `NOVA_LOCAL_SIM_MODEL`, `NOVA_LOCAL_SIM_KEY`, 선택 `NOVA_LOCAL_STREAM`이다. 가상 환자·진찰은 SIM 모델을 함께 사용하며 미지정 시 Doctor 설정을 따른다. 지침 사용 시 `NOVA_GUIDELINES_DIR`도 지정한다.

구형 키트는 Doctor 인자로 None/옛 별칭만 허용한다. `dev/local_agent.py`가 앱의 최신 지정 모델 인자를 검증 후 제거하여 키트 Endpoint의 실제 로컬 모델 설정을 사용한다. **제출 앱과 SDK의 모델은 바꾸지 않았다.** 어댑터는 제출 ZIP에 포함하지 않는다. 로컬 모델 실행은 서버 성능·공식 점수 재현이 아니다.

## 공개 샘플: 고정 6세션 비교

목적은 **v3.2(774항목) 대 v3.3(774+운영진 지침)**, C01·C10·C03 각 버전 1회다. Doctor 모델·Config·reasoning 설정은 동일하게 유지한다. 이전 원장 3/3은 읽어 복제하거나 수정하지 않는다.

저장소 루트에서:

```text
python -B -I scripts/run_public_comparison.py --baseline /path/to/v3.2-app --samples /path/to/nova-samples-2026 --output /private/comparison --remaining 9 --credit-percent 99.5 --no-active-samples
```

잔여 세션·크레딧은 실행 직전 팀 화면에서 확인한 값으로 바꾼다. 진행 중인 개발 샘플이 없음을 확인한 경우에만 마지막 플래그를 준다. 문서화된 팀 잔액 SDK API가 없어 사용자 확인값·시각을 기록하며, 서버가 한도·크레딧 부족을 반환하면 중단한다. 공식 채점에는 손대지 않는다.

`NOVA_DEV_KEY`가 없으면 터미널에서 숨김 입력한다. 키는 메모리·익명 파이프로만 전달한다. 실제 서버 통신·크레딧 사용이 발생한다. 별도 ledger의 6개 slot/request_id와 앱 해시를 고정하고 중복 lock, prepare 선검증을 적용한다. 생성이 불확실하면 **같은 request_id**로 상태를 확인한 후 중단하며 새 세션으로 대체하지 않는다. 진행 중/실패 slot이 남으면 다음 세션을 만들지 않는다.

Doctor는 시작 정보와 실제 SDK 상호작용만 받는다. 로컬 대본은 UUID를 연결하는 시작 정보 대조에만 사용하며 전체 대본·진찰표·모범 기록은 RAG/Doctor에 넣지 않는다. 원시 로그·새 원장은 반드시 Git 밖에 둔다. 버전·사례·설정·앱 해시·사용량·시간·최종 상태를 남긴다.

## 벤치마크와 평가

```text
python -B -I scripts/check_benchmarks.py --zip /path/to/nova-benchmarks-2026.zip --report /path/to/benchmark-smoke.json
```

`benchmark_adapters.py`는 Doctor 입력 허용 목록과 simulator/evaluator 자료를 분리한다. AgentClinic은 초기 증상·활력징후만 제공하고 TEST 결과·정답을 평가기에 둔다. 원래 과제의 TEST 허용과 예선 제약은 다르다. DDXPlus는 원래 train/validate/test와 행 번호를 보존하고 중첩 ZIP CSV를 스트리밍한다. 질문 코드·영어 질문·값 의미를 연결한다. ACI-Bench는 관찰 대화→기록 과제이며 정답 진단 점수를 만들지 않는다. 원문 영어를 사용했고 번역하지 않았다. 한국어 30자 행동 제한에서 진료 실행을 완료했다는 의미는 아니다.

seed `20261015`: AgentClinic 5개, DDXPlus 5개(2/1/2 split), ACI-Bench 5개(각 split 1개), 총 15개 ID를 보고서에 기록한다. 전체 CSV는 스트리밍으로 행 수를 확인하되 전체 모델 평가는 하지 않는다.

`evaluation_summary.py`의 영역은 정보수집 25·진단추론 15·검사/추적 10·안전 15·의사소통 15·효율 20이다. 성공한 행동 로그와 최종 기록을 함께 쓰며, 기록만 보고 실제 수행했다고 추정하지 않는다. 미평가 점수는 null이다. 검색 적절성·근거의 환자 사실 혼입도 임의 통과로 표시하지 않는다.

원시 로그에서 사례별 상태·사용량·시간·버전 차이만 추출하려면 다음을 실행한다. 환자 텍스트·세션 ID·키는 요약 파일에 복사하지 않는다.

```text
python -B -I scripts/summarize_public_comparison.py --runs /private/comparison --output /path/to/aggregate.json
```

6개 비교가 완료되고 자체 참고 평가가 필요하면 다음 도구가 세션 밖 `openai/gpt-6.1-sol`을 최대 3회 호출한다. 유료이며 별도 ledger와 request_id를 보존한다. 불확실한 호출을 새 요청으로 대체하지 않는다.

```text
python -B -I scripts/review_public_comparison.py --runs /private/comparison --samples /path/to/nova-samples-2026
```

자가평가는 공식 점수가 아니고 웹사이트 채점을 대체하지 않는다. 평가 입력의 근거는 마지막 패킷이므로 모든 시점의 검색 적절성으로 일반화하지 않는다.

## 검증과 패키지

`tests/test_extension.py`는 양 언어·완결 단위·길이·해시/경로·중복·부정·RAG 설정·개발 모델·정답 분리·행동/기록 구분을 검증한다. 기존 145개 테스트는 `scripts/run_v3_tests.py`로 실행한다.

`python -B -I tests/test_extension.py`와 `python -B -I tests/test_comparison_workflow.py`로 추가 테스트를 실행한다. 후자는 실제 API 없이 잔여 한도 차단·중복/불확실 세션 확인·비공개 출력 경로를 점검한다.

`probe_guidelines_runtime.py`의 socket guard와 OS 격리는 다르다. `linux_extension_supervisor.py`는 보존된 검증 도구의 cgroup·네트워크·진입점·종료 전 stdout/해시 반출 기능을 재사용하되, 대상과 manifest는 v3.3로 고정한다. 새 검증 결과는 `reports/extension_20261015/`에 둔다.

코드 ZIP은 app/ 내용만 루트에 넣는다. 원문·샘플 대본·벤치마크·개발 어댑터·키·로그는 제외한다. ZIP 생성이 공식 제출·권리 확인 완료를 뜻하지 않는다.
