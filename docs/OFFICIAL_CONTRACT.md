# 공식 계약 대조 (2026-10-15 KST)

[개발 가이드](https://nova.snubhai.org/docs/), [참가 규칙](https://nova.snubhai.org/rules/), [진행 및 평가](https://nova.snubhai.org/evaluation/), 제공 텍스트와 ZIP의 README·라이선스·실제 SDK를 확인했다.

| 항목 | 차이와 적용 |
|---|---|
| 현재 예선 Doctor | 10월 13일 공지·규칙은 `openai/gpt-6-luna`. SDK는 이전 ID를 Doctor 별칭으로 설명. 앱의 최신 명시 모델 유지 |
| 구형 개발 키트 | README는 `gpt-oss-20b`를 권하고 Simulator는 None/구형 ID만 허용. 개발 어댑터에서만 모델 인자를 제거하여 지정 로컬 Endpoint에 연결 |
| 상충 문장 | 웹 일부 문장의 제출 중 gpt-6-luna 호출 불가 설명은 같은 페이지의 세션 내 Doctor 및 현재 규칙과 충돌. 최신 지정 모델 공지·SDK 계약을 적용하고 운영진 해석을 대신 확정하지 않음 |
| 진찰 거절 | 키트 README에는 미차감 설명이 남아 있으나 실제 코드와 현재 규칙은 잘못된 EXAM에서 턴 차감 |
| 모델 역할 | 개발 샘플 환자·진찰/공식 평가: 안내상 gpt-6.1-sol. 제출 후 샘플 검증 환자·진찰·채점: gpt-6-luna. 로컬: 사용자 지정 Doctor/SIM 모델 |
| 실행 | 준비 600초·진료 1800초, CPU 2개·RAM 8GB, 런타임 다운로드 없음. 코드 ZIP 50,000,000바이트·해제 500,000,000바이트·5,000파일 |
| 평가 | 로그와 기록을 함께 사용. 비공개 세부 채점 프롬프트의 재현·동일성을 주장하지 않음 |

## 입력 해시

| 파일 | SHA-256 |
|---|---|
| 지침 ZIP | `ef58c2f4369750af382f2706dcc1c9c7a85e3a93c261d880f7470d695eaf30d5` — 공식 값 일치 |
| 벤치마크 ZIP | `a2b4dbc6a2bc177a54cf7c7f1a4e15f94625bfd335738737b575c6832a1060a7` — 공식 값 일치 |
| Downloads 샘플 ZIP | `2ffd8caea1e07b8616de67b5e15de72c08c1cc92b66da115fe40738658c581c4` |
| Desktop 샘플 ZIP | `b291b264c1e32a316132aa6bea1d999ebc8e13a9be9a6595c9af61a235e5ec23` |
| 개발 키트 ZIP | `074a80ac96e8bedd3565f698ad8ce15436ee22128955591d060ea9346f15c12b` |
| starter ZIP | `2f925653973e4d135be6d064ec13e4d255c4827e9b09d96ae510c27d0973def5` |

Downloads/Desktop의 지침·벤치마크·키트·starter는 각 쌍이 같다. 두 샘플 ZIP은 13개 샘플 파일이 같고 Desktop ZIP에 벤치마크 ZIP이 추가되어 있다. 순수 샘플은 Downloads ZIP을 썼다.

## 출처·처리·권리

- 운영진 지침: catalog·헤더 대조, 원문은 수정하지 않고 완결 구간을 읽는다. 검색 해시/빈도 생성은 별도 처리이며 이용 조건을 자동 해결하지 않는다. CC BY-NC-ND 10,352개, 공공누리 제4유형 932개 등을 포함한다. 개별 출처·라이선스를 반환한다.
- AgentClinic: Schmidgall 등 (2024), arXiv:2405.07960, 제공 기준 커밋 `b6fbe22300e99a267a7ac94eaa465ab552eef741`. 원천 MedQA: Jin 등 (2020), arXiv:2009.13081. 두 MIT 고지를 원본 ZIP에 보존한다.
- DDXPlus: Fansi Tchango 등, NeurIPS 2022, arXiv:2205.09148, [영어판 v2](https://doi.org/10.6084/m9.figshare.22687585.v2), CC BY 4.0. 원래 split/행 번호를 유지하고 코드를 질문과 답 의미에 연결한다.
- ACI-Bench: Yim 등, Scientific Data 10, 586 (2023), [v1](https://doi.org/10.6084/m9.figshare.22494601.v1), CC BY 4.0. split·encounter_id 및 대화/정답 기록 분리를 유지한다. 화자 표기 오류 가능성은 한계다.
- 번역·모델 데이터 생성·전체 유료 벤치마크 평가는 하지 않았다. 원문·환자 실행 원시 로그는 Git에서 제외한다. 기존 고지문 수정안은 미적용이다. 비공개 저장소와 단순 검색 인덱스가 권리 문제를 해결하는 것은 아니다.
