# NOVA v3.3 개발 확장 결과 — 2026-10-15

v3.2 기준으로 운영진 지침 RAG, 공식 개발 키트 어댑터, 공개 샘플 비교 및 벤치마크 평가 도구를 구현했다. **새 후보를 실제 Linux 제한 환경에서 별도로 검증했다.** 합성 검증은 진단 정확도·임상 기록 품질 평가나 비공개 대회 서버 동일성 검증이 아니다.

## 구현과 공식 기준

- [공식 docs](https://nova.snubhai.org/docs/), [rules](https://nova.snubhai.org/rules/), [evaluation](https://nova.snubhai.org/evaluation/), 제공 텍스트, ZIP README·라이선스·catalog/header·SDK를 확인했다. 모델 설명 차이는 [OFFICIAL_CONTRACT.md](../../docs/OFFICIAL_CONTRACT.md)에 기록했다.
- 제출 Doctor는 기존 `openai/gpt-6-luna` 그대로다. 개발 키트의 구형 모델 별칭 충돌은 제출 앱 밖 `dev/local_agent.py`에서 처리한다. 가상 환자·진찰 모델과 로컬 Endpoint 설정은 개발 키트에 따른다.
- 운영진 **15,904문서(영어 14,398·한국어 1,506)**를 연결했다. 10개 유형이며 catalog/header 불일치 0개다. 라이선스 집계는 [guidelines_build.json](guidelines_build.json)에 있다.
- 기존 774항목과 새 지침을 따로 선택할 수 있다. SQLite에는 메타데이터·원문 해시·해시된 검색어/빈도/문서 ID 목록을 저장하고 본문은 저장하지 않는다. 원문은 `NOVA_GUIDELINES_DIR`(서버 기본 `/opt/nova/guidelines`)에서 읽는다.
- URL·원문 해시·제목으로 중복 근거를 제외한다. 관찰/참고 분리·부정 표현·완결 H2/본문·12,000자 패킷 제한을 유지한다. 의미상 중복의 완전 제거·자동 번역·교차언어 의미 검색을 주장하지 않는다.
- 원문 전체·공개 사례 대본·정답·키·실제 세션 원장은 Git/코드 ZIP에 포함하지 않는다. 인덱스 생성이 자료별 이용 조건을 해소하지 않으며 외부 제출 조건은 여전히 미확정이다. 기존 rights/고지문 및 미적용 수정안을 보존했다.

## 새 버전 검증

| 검증 | 결과와 범위 |
|---|---|
| 기존 회귀 테스트 | Windows 및 새 Linux에서 **145/145**. 새 코드의 legacy 설정으로 실행 |
| 추가 검색/정보분리 테스트 | Windows 및 Linux **13/13** |
| 비교 원장 안전성 테스트 | Windows **4/4**. 부족 한도, 중복 생성 방지, 불확실 생성의 동일 request_id 확인, Git 밖 출력 |
| 실제 run.py·SDK 진입점 | 새 후보 합성 normal/recovery/uncertain **3/3**. 전송 계층만 mock, 실제 모델/API 호출 0 |
| 공식 develop.py | 실제 `load_agent()`·`prepare()` 연결 통과. C01/C10/C03 자료 로딩 확인. 로컬 모델 진료 미실행 |
| 벤치마크 | AgentClinic 5·DDXPlus 5·ACI-Bench 5 = **15/15** 파싱·허용 입력·매핑 점검. 모델 평가 미실행 |

Linux 원시 근거: [linux_validation.json](linux_validation.json), [linux_docker_settings.json](linux_docker_settings.json), [linux_raw/](linux_raw/), [linux_result_hashes.json](linux_result_hashes.json). 결과는 컨테이너 종료 전에 stdout으로 반출하고 각 파일 SHA-256 확인 후 Windows에 보존했다. Windows 원시 로그와 전체 Linux 반출 ZIP은 저장소 밖 `nova_extension_work_20261015/`에 있다.

환경: 기존 GCP `nova-rag-dev-20261015` / `nova-v32-validate-20261015` / `us-central1-a`, **e2-standard-4(4 vCPU·16GiB급)**, Ubuntu 24.04, Python 3.12.15. 보존된 이미지 `sha256:354e40c79e3579c61b8e56d4ae1abc65a5c1c9741dce207c29ab1e42d18c67a7`를 재사용하고 새 후보 파일을 읽기 전용 마운트했다. 이미지가 같아도 앱 버전은 다르며 실행 파일 해시를 별도로 기록했다. 설치·빌드·런타임 다운로드는 없었다.

| 제한 | Docker/컨테이너 내부 대조 결과 |
|---|---|
| CPU | NanoCpus=2,000,000,000 / `cpu.max=200000 100000` = 2개 |
| RAM | Docker Memory=8,589,934,592 / `memory.max=8589934592` = 8GiB |
| 추가 스왑 | MemorySwap=Memory / `memory.swap.max=0` |
| 네트워크 | `network=none`, loopback만 존재, default route 없음, 외부 연결/DNS 실패 |
| 파일시스템·사용자 | readonly root와 내부 `/proc/mounts`의 `ro` 대조, UID 65532, 원문/앱 읽기 전용 |
| 시간 | 준비 600초·진료 1,800초 제한 wrapper 적용 |
| 종료 | exit 0, OOM false, timeout false, 임시 컨테이너 삭제 확인 |

준비 전량 재색인 대신 사전 생성 인덱스를 선택했다. Windows 전체 색인 생성 239.765초, DB 91,832,320바이트. Linux runtime 준비 **0.467초**, 질의 4개 **0.743~6.297초**, 최대 패킷 **11,970자**, runtime process peak **150,937,600바이트**. 전체 검증 cgroup peak **315,666,432바이트(약 301MiB)**, 컨테이너 실행 약 **197.206초**다. 실제 긴 진료의 속도·메모리를 이 4질의 수치로 일반화하지 않는다.

## 공개 샘플 비교와 점수

고정 목적: **v3.2 774항목 대 v3.3 774+운영진 지침**, C01·C10·C03 각 2회, 최대 6개 새 세션. Doctor 모델·Config·reasoning은 동일하다. 사용자 확인값은 개발 크레딧 99.5%, 잔여 9회, 진행 중 개발 샘플 없음이다. 공식 채점에는 접근·취소·재제출하지 않는다.

실행 상태와 비교 수치는 [public_comparison.json](public_comparison.json)이 기준이다. 키가 준비되지 않은 항목은 `NOT_EXECUTED`, 실행 중/실패는 해당 상태를 그대로 남긴다. 새 원장·환자 로그는 Git 밖에 보존하며 이전 3/3 원장을 복제하지 않는다. 세션 생성이 불확실하면 원래 request_id로 확인하고 다음 세션을 중단한다.

여섯 영역(정보수집 25·진단추론 15·검사/추적 10·안전 15·의사소통 15·효율 20)의 결과표 생성 도구를 구현했다. 로그와 최종 기록이 없거나 검토하지 않은 점수는 null이며, 기록의 계획을 실제 행동으로 간주하지 않는다. 선택적 세션 밖 자체 비교 평가 도구는 최대 3요청으로 제한한다. 자체 평가는 공식 점수를 대체하지 않는다.

실제 비교 완료 전 검색 적절성·진료/기록 품질·토큰/호출 수·API 비용의 개선을 주장하지 않는다. 기존 calibration Recall@5 **1/6**은 기존 측정치이며 새 인덱스의 임상 성능 수치가 아니다.

## 벤치마크 범위

seed 20261015와 15개 사례 ID는 [benchmark_smoke.json](benchmark_smoke.json)에 고정했다. AgentClinic의 진단·TEST는 평가기, 대본·진찰표는 시뮬레이터만 읽는다. 예선에서는 원래 과제의 TEST 기능을 제공하지 않는다. DDXPlus 원래 train/validate/test를 유지하고 1,292,579행을 스트리밍하며 선택 5개만 어댑터 점검했다. ACI는 대화→기록 과제로 진단 정확도를 만들지 않는다. 영어 원문 그대로 사용했고 번역하지 않았다. 한국어 30자 제약하의 전체 모델 진료 통과를 의미하지 않는다.

## 비용·정리·보존

현재 확인한 e2-standard-4 단가 **$0.13402284/시간**, 임시 IPv4 **$0.005/시간**. 세 번의 시작~중지 작업 시간 합계로 계산한 보수적 추정은 compute **약 $0.02261**, IPv4 **약 $0.00084**다. 디스크 보유·전송·세금 등 제외, 실제 청구서가 아니며 기존 크레딧 적용은 확인 불가다. [비용/정리 기록](cloud_cost_and_cleanup.json), [공식 Compute 요금](https://cloud.google.com/products/compute/pricing/general-purpose).

첫 시도는 직접 SSH 제한으로 중단 후 IAP로 전환했다. 두 번째는 Docker socket 권한 문제로 컨테이너 생성 전에 중단했고 `sudo -n docker`로 해결했다. 각각 로그/중지를 보존했으며 같은 실패를 반복하지 않았다. 마지막 실행 성공 후 VM **TERMINATED**를 조회 확인했다. 기존 디스크·이미지·다른 VM은 삭제/변경하지 않았다. 로컬 Docker/WSL 설정도 바꾸지 않았다.

기존 후보 SHA-256 **831560900bd759a0af4260ec9af0b25dede46f98f2a3d293315e061464aceaf8** 및 기존 원장/승인 파일의 전후 해시 일치: [preservation.json](preservation.json).

새 코드 ZIP: `nova_extension_work_20261015/nova_doctor_bm25_candidate_v3_3.zip`, **44,987,790바이트·24파일**. SHA-256 **52ce53b0810e765ed2bb0c84338fe36fe7b4268ca7063dfc93f8cfc544dffe95**. [새 manifest](candidate_manifest.json). 50MB 이하이며 원문 전체를 포함하지 않는다. 공식 업로드·제출은 하지 않았다.

사용법: [EXTENSION_V3_3.md](../../docs/EXTENSION_V3_3.md). 개발 브랜치 `codex/nova-guidelines-evaluation`; main 병합·팀원 메시지 전송 없음.
