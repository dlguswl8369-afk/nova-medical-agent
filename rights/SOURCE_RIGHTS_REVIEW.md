# NOVA v3.2 자료별 외부 제출 이용 조건 검토

2026-10-15 KST. 대상은 고정 후보 `nova_doctor_bm25_candidate_v3_2.zip`의 실제 검색 자료 6개다. **현재 후보를 외부 제출 이용 조건 확인 완료로 표시할 근거는 부족하다.** 그렇다고 6개 자료의 모든 외부 이용이 금지된다는 뜻도 아니다. 공공누리·CDC의 조건부 이용 가능성과 현재 변환물의 조건 충족 여부를 구분해야 한다.

이번 작업은 원본·후보·검수 이력의 읽기 전용 조사와 이 별도 폴더의 보고서 작성만 수행했다. Linux 검증 재실행, VM 시작, 실제 NOVA API·샘플·제출·문의 전송은 하지 않았다. 기존 `doctor_agent_v3_2`와 후보·프롬프트·정책·원장은 수정하지 않았다. 보존 검증 결과는 `preservation-after.json` 참조.

## 핵심 결과

| 자료 | 실제 항목 수 | 새로 확인한 개별 근거 | 현재 남은 핵심 문제 |
|---|---:|---|---|
| 2026 질병코딩사례집 | 176 | 보존 PDF 1쪽 공공누리 제4유형, 3쪽 이용 유의사항, 209쪽 판권. 공식 서지 ISBN 일치 | 공식 파일 바이트 진위·최신판 대조, 진단 추론 목적 적합성, 현재 구조화물의 변경금지·대회 비영리성 |
| 2026 질병코딩지침서 | 173 | PDF 1쪽 제4유형, 3쪽 유의사항, 17쪽 이용 안내, 135쪽 판권. 공식 서지 ISBN 일치 | 위와 같음. 수록 정보는 진단기준이 아니라 코드 적용 참고라는 주의 |
| 2026년 법정감염병 진단·신고기준 지침 | 363 | 해당 KDCA 게시물 제4유형. 새 공식 PDF와 원본 SHA256 동일 | 추출·구조화·원문 포함 색인의 변경 여부, 대회·공개·출판 목적별 조건 |
| WHO Ebola disease | 25 | 2025-04-24 fact sheet와 웹사이트 약관. 현재 본문과 수집본 본문 동일 | 현 인덱스가 선택 본문 전체를 포함. 웹 발췌 허용만으로 이 범위를 승인할 수 없음. 개별 CC/서면 허락 미확인 |
| CDC Clinical Guidance for Ebola Disease | 29 | 2026-05-27, NCEZID 본문 출처 및 CDC 정책 | 고지 보완, 실질 내용 유지, 제3자·미국 외 권리와 구조화 구간 검토 |
| CDC Clinical Features of Ebola Disease | 8 | 2026-05-27, NCEZID 본문 출처 및 CDC 정책 | 위와 같음 |

총 **774개**이며 사용자 제시 수량과 일치한다. 자료마다 내부 연구 / 텍스트 추출·구조화·색인 / 대회 서버 업로드 / 독립 코드 공개 / 데이터 포함 공개 / 연구 출판을 구분한 표는 [SOURCE_EVIDENCE_MATRIX.md](SOURCE_EVIDENCE_MATRIX.md)와 그 안의 6개 개별 표에 있다. 공식 조건의 URL·위치·짧은 근거 문구는 [TERMS_EVIDENCE.md](TERMS_EVIDENCE.md)에 모았다.

## 원본과 후보의 동일성

PC의 실제 원본은 다음 보존 ZIP에서 찾았다.

`C:\Users\hjlee\OneDrive\Desktop\의료 agent\의료원본자료_16개.zip`

| 자료 | ZIP 내부 원본 | 후보 메타데이터 및 원본 SHA-256 |
|---|---|---|
| 사례집 | `kcd9/질병코딩사례집 2026.pdf` | `c8f86a29970ff6a01f9815c1b199466ca8fc3696d6f5e3099d8d637b786a9c80` |
| 지침서 | `kcd9/질병코딩지침서 2026.pdf` | `8a97d068f82a9399f9deec68f5b7af4e4a3f349f17b34b17cec7c83e05e5de7d` |
| KDCA | `kdca/2026_법정감염병_진단신고기준.pdf` | `8e51d489150bb7d3dd78feee132a7cab1f6c0be0d39d84cef41dc859dad19319` |
| WHO | `who_clinical/ebola_disease_2025.html` | `c0e59f01d57bdf54232d0ec478845a5fc9ea2a80c0886db14afca2058d7ed7b9` |
| CDC Guidance | `cdc_clinical/ebola_clinical_guidance_2026.html` | `b82e6f9964e767079e6cf62994f3f2688c27470bc23de4cf25e802ca81a2f54b` |
| CDC Features | `cdc_clinical/ebola_clinical_features_2026.html` | `e24d699084723a5c846a4a1943d6890398e1a12f9aafc5a2f993195bd40bbf04` |

6개 모두 원본 ZIP 바이트, 실제 후보 인덱스 각 레코드의 `source_sha256` 및 `source_metadata.sha256`과 일치한다. 후보 ZIP 자체는 지정 SHA256 `831560900bd759a0af4260ec9af0b25dede46f98f2a3d293315e061464aceaf8`과 일치한다.

이 대조는 **어떤 자료가 들어갔는지**를 확인한다. 해시가 같다는 이유로 이용허락이 성립하는 것은 아니다. 코딩 2권의 표지는 원본과 같은 PDF에서 직접 렌더링해 육안 확인했다. pypdf의 단순 텍스트 검색에서는 권리 표시가 검출되지 않았으므로 이를 ‘표시 없음’의 증거로 쓰지 않았다. PDFium 보조 추출과 실제 이미지 확인을 병행했다.

## 서지 확인과 이용허락 확인의 차이

공식 통계도서관에서 [사례집 서지](https://lib1.mods.go.kr/search/detail/CATTOT000000106137)와 [지침서 서지](https://lib1.mods.go.kr/search/detail/CATTOT000000106136)를 현재 조회했다. 국가데이터처·2026·ISBN 각각 9788958015550 / 9788958015543이 원본 판권과 일치한다. 두 PDF 판권에는 2026년 9월 발행으로 적혀 있다. 도서관은 본문 198쪽 / 120쪽, PDF는 앞부분과 판권을 포함해 209쪽 / 135쪽이다.

서지는 공식 발행물의 존재·신원에 대한 근거다. 서지 페이지 자체는 데이터 추출·서버 제출 허락서가 아니다. 이번 개별 이용조건 확인 근거는 **해시 일치 보존 PDF 표지의 제4유형 표시**다. 다만 공식 배포 PDF의 바이트를 직접 받아 코딩 2권과 대조하지는 못했다. 통계분류포털 주소는 HTTP 200이었지만 본문이 오류 안내라 공식 최신 파일 확인 성공으로 기록하지 않았다. `source_url=null`, `license_checked=false`는 원본 메타데이터에 그대로 보존했다.

KDCA는 [개별 게시물](https://www.kdca.go.kr/bbs/kdca/55/311073/artclView.do?layout=unknown)의 상세 조건 문장과 [현재 첨부 PDF](https://www.kdca.go.kr/bbs/kdca/55/307100/download.do)까지 확인했다. 기관 일반 정책을 해당 문서의 허락으로 대신하지 않았다.

WHO는 일반 웹 fact sheet다. [웹사이트 약관](https://www.who.int/about/policies/terms-of-use)과 [출판물 정책](https://www.who.int/about/policies/publishing/copyright)을 분리했으며, 후자의 CC 조건을 이 자료에 자동 적용하지 않았다. CDC는 [기관 정책](https://www.cdc.gov/other/agencymaterials.html)과 두 개별 페이지의 출처·예외 표시를 함께 검토했다. NCEZID 출처와 본문에 별도 권리 고지가 발견되지 않은 점은 적용 가능성을 뒷받침하지만, 모든 계약자·제3자 권리 및 미국 외 이용을 확정하는 증거는 아니다.

## 후보가 실제로 포함하는 것

이 후보의 인덱스는 토큰 빈도와 위치만 저장하지 않는다. 774개 레코드 모두 `text`와 `original_text`가 있으며 출처 메타데이터·사례 구조·근거 필드를 포함한다. 후보의 `assets/evidence_units.json`도 원문 근거 단위를 담는다. 따라서 인덱스 업로드와 공개는 단순한 알고리즘 코드 이전으로 볼 수 없다.

WHO 25개 항목의 공백 제거 후 정확히 일치하는 원문 구간의 합집합은 선택된 HTML 본문 **10,155/10,155자, 100%**다. 사진·메뉴·사이트 전체를 말하는 수치가 아니며 법률상 ‘상당 부분’의 수치 기준도 아니다. 다만 ‘25개 발췌’라는 개수만으로 짧은 일부 이용이라고 판단해서는 안 된다는 구체적 근거다. [계산 결과](who-text-coverage.json).

CDC의 동일 방식 연속구간 대조는 Guidance 28/29, Features 6/8이었다. 섹션 조합·생략·문자 처리로 연속구간 검사가 실패할 수 있으므로 이 결과를 곧바로 내용 왜곡이라고 하지는 않는다. 반대로 이 간단한 검사만으로 구조화·검색 결과의 의미 유지가 확인됐다고도 하지 않는다. 현재 고지문 변경만으로 이 검토가 완료되지는 않는다.

공공누리 자료도 기계적 포맷 변환·원문 그대로의 검색과 표·사례의 재구성 사이에 적용 판단이 필요하다. 출처 보존은 필요하지만 그것만으로 변경금지 조건 충족을 보장하지 않는다. 상금·후원·영리 사업자 클라우드 사용이 있는 대회의 비영리성도 자동 판정하지 않았다.

## INTERNAL_ONLY / external_redistribution_allowed=false의 경위

현재 보존 자료로 확인되는 생성 경로는 다음과 같다. 원래 설정을 누가 어떤 대화에서 최초 결정했는지는 별도 증거가 없어 특정하지 않는다.

1. `input_package/NOVA_RAG_전체수정/project/config/sources.json`에 각 자료의 `external_redistribution_allowed=false`가 명시돼 있다. 코딩 2권은 `license_checked=false`, `llm_processing_allowed=false`, `LATEST_REVISION_LISTING_CONFIRMATION_REQUIRED`도 갖는다. CDC 등 허용 경로가 있는 자료에도 외부 플래그 false가 들어 있으므로 이것 자체가 발행기관의 전면 금지 목록은 아니다.
2. 같은 프로젝트의 `medical_rag/collector.py:80`은 수집 문서에 `distribution='INTERNAL_ONLY'`를 직접 기록한다. `register_local(spec)`에서 내부 수집 정책으로 만들어지는 값이다.
3. `medical_rag/exporter.py:52` 이후의 외부 export 분기는 `external_redistribution_allowed is True`인 자료만 통과시킨다. 내부 확인 전 원문이 외부로 나가지 않도록 하는 소프트웨어 필터의 증거다. False 값만으로 법적 금지 사실을 증명하지 않는다.
4. 별도 `config/research_usage_policy.json`과 `medical_rag/research_export.py:231–249`는 최신 코딩자료의 사례·원문 검색을 연구용으로 허용하고 과거 검수 결과를 보존한다. 이는 발행기관이 발급한 허락서가 아니다.
5. 현재 v3.2의 `policies/source_usage_inventory.json`, `app/assets/research_policy.json`, `app/ASSET_NOTICE.md`는 내부 연구 승인과 외부 제출 `UNCONFIRMED`를 구분한다. 현재 코딩자료의 원문 플래그는 유지되며 버전 확인 게이트만 연구 범위에서 별도로 해석됐다는 이력이 있다.

`policies/provenance_manifest.json`의 보존 사본 해시도 원래 설정/생성 코드와 대조했다(`provenance-verification.json`). 이번에 내부 플래그를 외부 제출 가능으로 바꾸지 않았다. 원본 표지에서 새로 확인한 제4유형과 사용 목적 안내는 내부 코드와 독립적인 발행물 근거로 추가했다.

## 검수 이력의 의미

`data_final/audit`와 `data_final/evidence`, v3.2 provenance를 찾고 해시를 기록했다. 원래 42개 주장과 42개 AI 검수 이력은 그대로 보존돼 있다. AI 임시 승인 18, 검토 필요 14, 거절 10이라는 집계는 내용 검수 이력이다. 자료별 집계는 `history-status-counts.json`에 있다. 코딩 2권은 이 42개 주장 집합에 들어 있지 않더라도 연구 검색용 원문·사례가 별도로 들어간다. 이번 실제 검색 항목 774개와 과거 주장 42개를 같은 수량으로 해석하지 않는다.

AI 승인·원문 대조·기관 확인·임상 검수·외부 이용허락은 서로 다른 판단이다. 어느 하나의 통과도 나머지를 대신하지 않는다.

## ASSET_NOTICE 검토

현재 파일은 내부 배포 상태와 연구 승인 범위를 설명하는 점은 적절하다. 그러나 다음은 부족하다.

| 항목 | 현재 파일 | 별도 수정안 |
|---|---|---|
| 6개 자료의 명시적 출처·직접 링크 | 메타데이터에 있다는 설명만 존재 | 자료명·기관·버전·링크를 문서에 기재 |
| CDC 비보증 고지 | 명시적 고지 없음 | CDC/ATSDR/HHS/미국 정부의 승인·후원 아님을 눈에 띄게 기재 |
| CDC 무료 원문 안내 | 없음 | 해당 CDC URL에서 무료 제공됨을 기재 |
| 실질적 내용 유지 | 원본 인덱스 보존 주장만 있음 | 실제 구조화물 점검 필요와 미해결 상태 구분 |
| 공공누리 유형과 목적 안내 | 각 자료 조건·주의가 본문에 없음 | 확인된 유형·유의사항·추가 확인 필요 명시 |
| WHO 웹페이지/출판물 조건 구분 | 명시적 구분 없음 | fact sheet에 CC를 자동 부여하지 않음 |
| 버전·검증 설명 | 제목은 v2, 구조 검증 중심 | v3.2와 현재 권리 조사 상태를 구분 |

[ASSET_NOTICE_PROPOSED.md](ASSET_NOTICE_PROPOSED.md)는 **별도 검토안이며 기존 후보에 적용하지 않았다**. 고지문 보완만으로 변경금지·허락 범위·제3자 권리 문제가 해결되지는 않는다. 코딩 2권의 공식 무료 원문 링크는 미확인이므로 이를 꾸며 넣지 않았다.

## 다음 판단에 필요한 답변

[INQUIRY_DRAFTS.md](INQUIRY_DRAFTS.md)에 국가데이터처, KDCA, WHO, CDC, NOVA 운영진에게 보낼 수 있는 구체적 초안을 작성했다. 연락하거나 전송하지 않았다. 필요한 것은 단순한 ‘AI 사용 가능 여부’가 아니라 현재 자료·분량·가공 방식·서버 업로드·공개·논문 부록 범위에 대한 답변이다.

특히 [NOVA 규칙](https://nova.snubhai.org/rules/)의 검색 자산 허용은 기술 규격이며 저작권 승인이 아니다. 연구 출판이 가능해야 한다는 조건이 전체 데이터 공개까지 뜻하는지, 제한 자료를 서버 내에서만 사용하는 제출도 인정되는지, 운영진·클라우드의 보관/재사용 범위를 확인해야 한다. 앞선 GCP 검증도 실행 증거일 뿐 자료 이용권한을 소급하여 확정하지 않는다.

## 산출물과 확인 범위

- [6개 자료 근거표](SOURCE_EVIDENCE_MATRIX.md): 자료별 확인 조건·해석·미확인 사항.
- [공식 조건·짧은 인용·페이지](TERMS_EVIDENCE.md).
- [고지문 수정안](ASSET_NOTICE_PROPOSED.md), [문의문 초안](INQUIRY_DRAFTS.md).
- `local-source-evidence.json`, `candidate-source-analysis.json`, `web_evidence/`, `evidence/`: 해시·원본 위치·공식 수집 근거·실제 PDF 페이지 이미지.
- `preservation-before.json`, `preservation-after.json`, `SHA256SUMS.txt`: 기존 파일 보존과 새 보고서 무결성.

현재 WHO 본문은 수집본과 같지만 일반 HTML 동적 요소 때문에 전체 파일 해시는 달랐다. CDC 웹 읽기는 성공했으나 로컬 직접 저장은 403이었다. 코딩 공식 서지는 직접 HTTP로 확인했으나 통계분류포털의 최신 원문 연결은 오류였다. 이러한 한계를 숨기거나 허락 확인으로 바꾸지 않았다.
