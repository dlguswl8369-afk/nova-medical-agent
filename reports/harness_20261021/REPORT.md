# NOVA 개발 하네스 구축 결과

2026-10-21. `codex/nova-development-harness`, 기준 `81714d340207a8e5ca9886dd2129cbd6b9cc61f2`.
별도 작업 디렉터리 `nova-medical-agent-harness`를 사용했다. 시작 당시 원래 디렉터리는 v3.8 브랜치이며 loop.py/prompts.py/coverage.py 3개가 미커밋 상태였다. 그 바이트 해시·브랜치를 그대로 보존했고 v3.8 작업을 재개하지 않았다.

| 변경 파일 | 내용 |
|---|---|
| AGENTS.md | 작업 범위·승인·보존·품질 보고 원칙 |
| docs/HARNESS.md | 아키텍처, 명령, 기술적 차단과 한계, CI 존재 확인 |
| docs/EVALUATION.md | 정보수집·의사소통의 적용 조건과 근거 연결 형식 |
| docs/EXPERIMENTS.md | v3.3~v3.7 관측·변경·한계; v3.8 미완성 상태 구분 |
| harness/baselines.json | 고정 커밋을 읽기 전용 비교 대상으로 선택 |
| harness/cases/example.json | 합성 검토 사례와 8개 조건부 질문; 비공개 채점 정답 아님 |
| scripts/dev_harness.py | baseline/보호 AST 사전 검사, 오프라인 worker, 기존 회귀 재사용, 상태·근거 보고 |
| tests/test_dev_harness.py | 새 하네스 공백 5개 검사 |
| README.md / .gitignore | 하네스 안내 링크·새 실행 출력 Git 제외 |
| 본 폴더 | 검증 집계·실패 수정 이력·보존 증거 |

**진료 app 전체가 v3.5와 바이트 동일하다.** STEP/RECORD·모델·RAG·SDK·예산 변경 없음. 기존 후보·로그·원장 등 18개 해시와 v3.8 미커밋 3개 해시를 읽기 전용 확인했다. 원장 초기화·복제, 실제 진료/웹사이트/제출, Docker/GCP, main 병합 없음. 새 ZIP이나 유료 가능 CI는 만들지 않았다.

검증: 기존 회귀 **55/55 PASS**, 새 하네스 **5/5 PASS**. 최초 59개 중 예시 JSON 닫는 괄호 누락 1건을 수정했고 하네스 묶음만 재실행했다. 수정한 진료 코드가 없으므로 기존 회귀는 반복하지 않았다. baseline이 다른 실제 v3.8 디렉터리를 지정했을 때 **예상한 FAIL**과 worker 미실행을 확인했다. 합성 사례 형식 검사도 통과했다. 항목별 테스트 ID·결과는 [validation.json](validation.json)에 있다.

worker 내부에서는 감사 가능한 Python 네트워크·자식 프로세스·출력 폴더 밖 파일 변경을 거부한다. baseline 불일치 및 보호한 코드/설정 변경도 검사 시작 전에 거부한다. **직접 실행한 기존 스크립트·브라우저·native 코드까지 막는 OS 보안 경계는 아니다.** 임상 품질, 승인 진위, 외부 작업 비용·제출은 사람 검토 대상이다. 전체 상태는 REVIEW, 실제 진료 품질은 NOT_EVALUATED다.

현재: `python -X utf8 -B -I scripts/dev_harness.py check`

향후 별도 v3.8 개발 지시 후: `python -X utf8 -B -I scripts/dev_harness.py check --repo ../nova-medical-agent --baseline v3.5 --candidate`

명령은 이 하네스 작업 디렉터리에서 실행한다. 자세한 실행 경로·부분 검사 방법은 [HARNESS.md](../../docs/HARNESS.md)를 따른다. 이 명령이나 `--candidate` 자체는 임상 API 실행 또는 개발 재개 승인이 아니다.
