# 공식 조건 근거집

조회일: 2026-10-15 KST. 조건의 존재와 해당 이용행위에 대한 적용 판단은 구분한다. 아래 짧은 인용 외 설명은 요약이다. 자료별 표에서 이 근거 ID를 참조한다.

## K4 — 공공누리 제4유형

[공식 유형·약관](https://www.kogl.or.kr/info/licenseType4.do), ‘제4유형’, ‘저작물 사용 조건’, ‘출처 표시 의무’ 항목.
짧은 근거: **“출처 표시 + 상업적 이용금지 + 변경금지”**.
비영리·출처표시·변경금지 조건을 충족한 공유와 이용은 허용된다. 온라인 링크 제공, 후원으로 오인시키지 않는 표시도 요구된다. 변경·2차적 저작물 작성은 기본 허용에서 제외되며 별도 허락이 가능하다. 단순 포맷 변환·색인과 재구성의 경계, 상금·협찬·상업 클라우드가 있는 대회의 비영리성은 이 페이지가 판정하지 않는다. 모든 외부 배포가 금지된 라이선스로 해석하지 않는다.

로컬 증거: `web_evidence/kogl4.html`, 조회 manifest의 SHA256. 코딩 2권은 원본 표지 표시로, KDCA는 개별 게시물 표시로 이 조건과 연결한다. 기관 전체에 일괄 적용하지 않는다.

## K1/K2 — 국가데이터처 코딩 자료의 개별 표시

원본 ZIP `의료원본자료_16개.zip`의 2026 사례집·지침서 각각 **PDF 1쪽**에 OPEN 공공누리와 출처표시·상업적 이용금지·변경금지 세 아이콘을 육안 확인했다. 표지는 텍스트 추출만으로 검출되지 않았다. 각 `evidence/<document_id>/page_001.png`가 근거다.

사례집 PDF 3쪽 ‘이용시 유의사항’ 3항: **“코드 적용 측면에서만 활용되어야 합니다.”** 4항은 가상 사례이며 실제 사례와 다를 수 있음을 설명한다. 지침서 PDF 3쪽 3항: **“진단의 기준이 될 수 없습니다.”** PDF 17쪽(인쇄 3쪽)의 ‘질병분류지침서 이용 안내’도 KCD 분류 목적을 설명한다. 이는 저작권 표시와 별개의 내용·목적 주의이며, 문구만으로 모든 AI 이용의 법적 금지라고 단정하지 않는다. 현재 진단 추론 보조 사용과의 정합성은 발행기관 질문에 포함한다.

판권: 사례집 PDF 209쪽 / 지침서 PDF 135쪽. 발행처 국가데이터처, 발행일 2026년 9월, ISBN 각각 978-89-5801-555-0 / 978-89-5801-554-3. 공식 도서관 서지의 제목·기관·연도·ISBN과 일치한다. 공식 PDF 직접 다운로드와 바이트 대조는 미확인이다.

## K3 — KDCA 개별 게시물

[2026년 법정감염병 진단·신고기준 지침 게시물](https://www.kdca.go.kr/bbs/kdca/55/311073/artclView.do?layout=unknown) 하단에 K4 조건이 명시되어 있다. 게시일 2026-05-14, 수정일 2026-05-15, 감염병정책과. 첨부 PDF를 새로 받아 SHA256을 대조한 결과 후보 원본과 일치했다. 게시물의 아이콘 대체문구만 보지 않고 상세 조건 문장을 확인했다.

근거: `web_evidence/kdca_post_windows.html`, `web_evidence/kdca_official_current.pdf`; 보존 당시 게시물은 `evidence/historical_catalogs/2026_진단신고기준_공식게시물.html`. PDF 1쪽은 2026.5 표지다. 앞 5쪽·뒤 4쪽 및 키워드 관련 페이지를 렌더링했고, KDCA PDF는 표지 1쪽과 끝 237쪽을 육안 확인했다. 이용허락의 핵심 근거는 개별 공식 게시물이다. PDF 전체의 모든 이미지·제3자 요소에 대한 권리 감정은 아니다.

## W1 — WHO 웹사이트 약관

[Terms of use of the WHO website](https://www.who.int/about/policies/terms-of-use), Copyright notice 본문.
짧은 근거: **“Extracts”**, **“explicit, prior authorization in writing”**.
연구·개인학습을 위한 발췌 검토·복제·번역은 비상업적 범위에서 허용하며, WHO와 해당 URL을 표시한다. 상당 부분 복제·번역 또는 교육·비상업 목적 밖의 이용에는 사전 서면 승인을 요구한다. ‘상당 부분’의 법적 수치 기준이나 이 대회의 성격은 명시하지 않는다. 현재 인덱스의 25개 WHO 항목은 합집합으로 보존 HTML의 선택된 본문 전체를 포함하므로, 소량 발췌 허용만으로 현재 산출물까지 허용됐다고 결론내리지 않는다.

근거: `web_evidence/who_terms.html`; 해당 자료는 [Ebola disease](https://www.who.int/news-room/fact-sheets/detail/ebola-disease) / 2025-04-24 웹 fact sheet다. 현재 웹페이지 전체 바이트는 수집본과 다르지만 선택 본문 텍스트는 공백 정규화 대조에서 동일했다. 사진(WHO/L. Mackenzie)과 참고문헌의 제3자 자료까지 이용허락된 것으로 간주하지 않는다.

## W2 — WHO 출판물 정책과의 구별

[Copyright, Licensing and Permissions](https://www.who.int/about/policies/publishing/copyright)은 실제 CC 조건으로 발행된 자료에 대한 정책이다. 이 fact sheet의 개별 CC 표시는 확인하지 못했다. 따라서 CC BY-NC-SA 3.0 IGO를 이 웹페이지에 자동 부여하지 않는다. 원래 `license_checked=true`와 출판물 정책 URL은 이러한 개별 허락의 증거가 아니다.

## C1 — CDC 자료 정책

[Use of Agency Materials](https://www.cdc.gov/other/agencymaterials.html), 본문 첫 3문단과 번호 1–4, CDC LOGO 항목.
짧은 근거: **“Attribution”**, **“does not imply endorsement”**, **“may not change the substantive content”**, **“for no charge”**.
대부분의 CDC 자료는 public domain이지만 제3자·계약자·지원기관·주/지방정부 저작물은 예외다. 미국 외 이용의 권리도 별도 확인 대상이다. 적용 가능한 CDC 본문은 출처, 두드러진 비보증 고지, 실질적 내용 유지, 무료 원문 안내를 갖춰 이용한다. 로고는 별도 서면 허락 없이 사용하지 않는다. 특정 단락의 저작권 표시가 없다는 사실만으로 권리 관계를 완전히 확정하지 않는다.

CDC 직접 HTTP 저장은 403으로 실패했지만 공식 URL의 웹 읽기 도구에서 위 항목을 확인했다. 실패 사실은 `web_evidence/fetch_manifest.json`에 보존했다. 두 원본 HTML은 수집 ZIP과 해시가 일치한다. C2: [Clinical Guidance](https://www.cdc.gov/ebola/hcp/clinical-guidance/index.html), C3: [Clinical Features](https://www.cdc.gov/ebola/hcp/clinical-signs/index.html); 두 페이지 모두 2026-05-27, Content Source는 CDC NCEZID. 실제 검색 범위의 본문에 독립적인 제3자 저작권 고지는 발견하지 못했으나 C2의 외부 논문 참고문헌·그림, C3의 이미지까지 포괄 허용한다고 보지 않는다.

## N1 — NOVA 참가 규칙

[참가 규칙](https://nova.snubhai.org/rules/), ‘제출 규격’ 및 ‘자료 이용·보안’.
짧은 근거: **“연구 출판에 사용할 수 있는 라이선스를 확인”**.
한도 내 검색 인덱스 사용은 기술적으로 허용되지만 원자료 권리를 새로 부여하지 않는다. 출처·생성 과정 및 재현 코드 보존, 운영진 제공 지침도 문서별 조건 준수를 요구한다. 원문 포함 인덱스의 외부 서버 업로드, 운영진 검토, 보관·재배포 범위가 이 후보에 어떻게 적용되는지는 별도 확인이 필요하다.

로컬 증거: `web_evidence/nova_rules.html`. 로그인·API·업로드·문의 전송 없이 공개 규칙만 읽었다.
