# 기존 Linux 검증 결과 요약

기존 2026-10-15 검증 기록만 요약했다. 이번 인계 포장 중 테스트·API·VM 실행은 없다.

- 환경: GCP 임시 e2-standard-4(4 vCPU, 16 GiB), Ubuntu 24.04, Docker 29.9.1, 컨테이너 Python 3.12.15.
- 이미지: `sha256:354e40c79e3579c61b8e56d4ae1abc65a5c1c9741dce207c29ab1e42d18c67a7`. 클라우드에서 빌드한 이미지이며 과거 Windows 로컬 이미지와 동일하다고 주장하지 않는다.
- 후보 SHA-256: `831560900bd759a0af4260ec9af0b25dede46f98f2a3d293315e061464aceaf8`.
- 합성 진료: normal/recovery/uncertain **3/3 PASS**. 실제 `run.py` 및 SDK 진입점을 사용하고 transport만 mock; 실제 API 호출 0.
- 기존 테스트 **145/145 PASS**, 실패 0, 오류 0. 테스트 64.258초, 전체 77.244초.
- Docker 설정 및 내부 cgroup v2: CPU 2개(`cpu.max=200000 100000`), RAM 8 GiB(`memory.max=8589934592`), 추가 스왑 0(`memory.swap.max=0`). Docker `--memory-swap`은 RAM+swap 합계로 8589934592.
- `network=none`, `pull=never`, 읽기 전용 루트, UID 65532. 내부 lo만 존재, 기본 경로 없음, 연결/DNS 차단 관측; 루트 쓰기 금지 확인.
- 준비 600초·진료 1800초 제한 적용. 종료 코드 0, OOM false, 시간 초과 없음. cgroup 관측 최대 메모리 285577216 bytes(약 272.35 MiB), oom/oom_kill 0.
- 원래 검증 후 임시 컨테이너 정리 및 VM 중지 기록 있음. 이 인계에서는 클라우드 현재 상태를 다시 조회하지 않았다.
- 진단 정확도·기록 임상 품질·비공개 대회 서버 동일성 평가가 아니다.

원본 복사: [통합 result.json](result.json), [컨테이너 결과](container_result.json), [145개 테스트 집계](suite/results.json), [기록 예산 시나리오](suite/record_headroom_scenarios.json), [행동 복구 시나리오](suite/action_repair_scenarios.json).
기존 결과 안의 `/tmp/verify/…` 및 `/home/hjlee/…` 경로는 당시 실행 경로다. 원본은 프로젝트 `doctor_agent_v3_2/validation/linux_container_20261015/reports/gcp_execution_20261015/`에 보존되어 있다.
