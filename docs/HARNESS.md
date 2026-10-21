# Offline development harness

이 문서는 개발 경계·아키텍처·로컬 검사 안내다. 진료 코드의 규칙은 기존 [공식 계약 대조](OFFICIAL_CONTRACT.md), [실행 설명](../README.md), [v3.5 보고서](../reports/v35_simple_20261016/REPORT.md)를 재사용한다. 공식 계약 문서의 확인일은 2026-10-15이며 이번 작업에서 최신 웹 규칙을 다시 검증하지 않았다.

## 구조

```text
AGENTS.md                         작업 범위와 사람 승인 원칙
harness/baselines.json             수정하지 않는 Git 커밋 선택표
harness/cases/example.json         합성 평가 사례; 실제 진료 입력으로 실행하지 않음
scripts/dev_harness.py             baseline/보호 코드 검사 → 격리된 Python 검사 프로세스 → 근거 보고
tests/test_dev_harness.py          신규 하네스의 공백만 검사
scripts/clinical_review.py         로컬 근거 연결·실제 행동/기록 대조, 임상 자동 점수 없음
harness/cases/clinical_review.json 검토 카탈로그, 원본 해시·포인터와 사람 검토 조건
harness/cases/clinical_synthetic.json 부족한 조건을 보충하는 수작성 합성 사례
tests/test_clinical_review.py      근거 누락·오연결·유출·허위 PASS 방지
docs/EVALUATION.md                 사례·평가 근거·상태의 의미
docs/EXPERIMENTS.md                버전별 관측과 한계
reports/harness_runs/<새 ID>/      매 실행 출력, Git 제외, 기존 파일 덮어쓰기 없음
```

진료 아키텍처는 `run.py → prepare → consult/Run → SAY/EXAM → 원문 관찰 → RECORD → DIAGNOSE` 그대로다. 검색 참고자료와 현재 환자 관찰은 분리되고, 설명은 SDK 성공 이후 저장된다. 하네스는 app에서 import되지 않으며 모델 호출·후보 ZIP 생성·제출 기능이 없다. 기존 `scripts/benchmark_adapters.py`의 Doctor/시뮬레이터/평가자 입력 분리를 재사용한다.

## 실행

Python 3.12와 표준 라이브러리만 사용한다. 설치 작업은 필요 없다. 하네스 작업 디렉터리에서:

```powershell
python -X utf8 -B -I scripts/dev_harness.py check
python -X utf8 -B -I scripts/dev_harness.py case-check --case harness/cases/example.json
```

이 PC에서 `python`이 없다면 `../nova_rag_dev_20261015/doctor_agent_v2/validation/python312/python.exe`를 사용한다. `--baseline v3.5`가 기본이다. 다른 등록 버전 선택은 **비교 대상만 변경**하며 checkout/reset/fetch를 하지 않는다. 실행할 app이 baseline과 다르면 기본 모드에서 테스트 전에 FAIL한다. 옛 버전은 현재 테스트와 계약이 다를 수 있으므로 자동으로 호환성을 가정하지 않는다. v3.7 Git 트리는 기본 선택이 baseline이며 A/B/C ZIP의 고정 선택 설정과 다르다.

향후 사용자가 v3.8 개발을 명시적으로 지시했을 때, 현재 원래 작업 디렉터리를 검사하는 명령:

```powershell
python -X utf8 -B -I scripts/dev_harness.py check --repo ../nova-medical-agent --baseline v3.5 --candidate
```

`--candidate`는 loop.py/STEP와 새 nova_agent Python 모듈의 차이를 REVIEW로 허용하는 **검사 범위 선택**이며 개발·유료 실행 승인이 아니다. SDK·RAG·기존 보호 모듈 변경은 거부한다. 편집 허용 파일 안의 MODEL/Config/prepare/Doctor 요청·행동 전송·시간 계산 및 RECORD도 AST로 기준과 대조한다. 임상 제어 흐름 변경의 적정성이나 새 모듈의 우회 동작까지 증명하지는 못한다.

초기 관련 묶음은 60개였으며 2단계에서 임상 검토 도구 테스트 12개를 추가했다. 수정 후 해당 부분만 필요하면 `--group harness`, `--group clinical_review`, `--group action_observation_delivery`, `--group final_record_budget`, `--group accounting`, `--group repair`, `--group evaluator_separation` 중 선택한다. 여러 group을 지정할 수 있다. 기존 전체 테스트는 자동 반복하지 않는다. 대상 repo의 기존 테스트와 app을 불러오며 보고서에 실제 import 경로를 기록한다. 근거 대조 명령 `review`와 사례/판정 형식은 [EVALUATION.md](EVALUATION.md)를 따른다. `review`에도 네트워크·프로세스·출력 외 쓰기 audit guard를 적용하며 app을 import하지 않는다.

## 기술적으로 차단하는 것과 경계

| 구분 | 실제 동작 |
|---|---|
| baseline 및 보호 코드 | Git blob 바이트 해시와 AST 비교 실패 시 검사 worker 시작 거부. app의 새 파일·누락·심볼릭 링크도 검사 |
| 네트워크·프로세스 | worker 시작 시 Python audit hook 설치. socket 이벤트, subprocess.Popen, os.system/exec/spawn 거부. 훅 설치 자체도 검사 |
| 파일 쓰기 | Python에서 감사 가능한 파일 쓰기·삭제·이동은 새 검사 출력 폴더 안으로 제한. app 파일은 검사 전후 해시 대조 |
| 실제 API/웹사이트/제출 | 하네스에 실행 명령·승인 토글 없음. 기존 실제 실행 도구를 자동 호출하지 않음 |
| 계약·기록·예산 | 기존 mock 회귀 테스트 재사용. 부적합한 TEST, 30자 초과, 근거 ID 혼입, 허위 설명 완료, 기록 예약·재시도 위반의 재현 사례를 검사 |
| 사례 구조 | 입력 허용 키, 관찰 종류, 중복 ID, 상태 값, 판정 근거 참조를 검사. 정답·완료율·임상 의미 판정은 하지 않음 |

**OS 샌드박스가 아니다.** native 확장·다른 프로세스·직접 실행한 기존 스크립트·브라우저는 이 프로세스 훅의 보호 대상이 아니다. 훅을 설치하지 않은 직접 명령을 저장소 전체에서 막는다고 주장하지 않는다. 승인 여부의 진위, 비용 발생 작업, 임상 적절성, 자료 이용 조건, 공식 제출은 AGENTS.md와 사람 검토에 의존한다. 외부 작업 승인은 이 하네스 밖에서 직접 받은 뒤 범위를 다시 확인해야 한다.

추적된 `.github/workflows`와 AGENTS.md는 기준 v3.5에 없었다. 기존 로컬 실행기·테스트·계약 문서·보고서는 있었다. 새 유료 가능 CI나 push-trigger workflow는 추가하지 않았다. GitHub 외부 설정은 조사하지 않았다.

보고서 전체 상태는 자동 실패가 있으면 FAIL, 자동 검사가 통과해도 임상 검토가 남으므로 REVIEW다. 종료 코드는 자동 실패일 때 1, 그렇지 않으면 0이다. 0이나 PASS인 개별 검사를 실제 임상 품질 인증으로 해석하지 않는다.
