# 쿠팡 검색 API 계약 대조

2026-09-10 Chrome에서 [쿠팡 파트너스 공식 가이드](https://partners.coupang.com/#help/open-api)의 **문서 → v1 → /products/search**를 직접 열어 확인했다. 이전 기록의 ‘공식 본문 대조 미완료’를 이번 확인으로 해소한다. 실제 인증 키로 쿠팡 API를 호출한 것은 아니다.

| 항목 | 공식 문서에서 확인한 계약 | 구현 대조 |
|---|---|---|
| 경로 | GET `/v2/providers/affiliate_open_api/apis/openapi/v1/products/search` | 모의 요청 대상과 일치 |
| 필수 입력 | `keyword`: 문자열 | 일치 |
| 선택 입력 | `limit`: 정수, 최대·기본 10 | 앱은 5를 명시해 사용; 스키마 최대 10 |
| 선택 입력 | `subId`, `imageSize`: 문자열 | 일치 |
| 선택 입력 | `srpLinkOnly`: 불리언, 기본 false | 일치 |
| 성공 응답 | `rCode`, `rMessage`, `data` | 일치 |
| data | `landingUrl`, `productData` | 일치 |
| 상품 | `keyword`, `rank`, `isRocket`, `isFreeShipping`, `productId`, `productImage`, `productName`, `productPrice`, `productUrl` | 필드·자료형 대조 완료 |
| 링크 전용 | 상세 상품 목록 없이 검색 링크 제공 | 목록이 없는 모의 응답 확인 |
| HTTP 오류 | 400, 403, 429, 500 | 입력 거절·전송 오류 시나리오에 대응 |
| 호출 한도 | 검색 API 분당 50회 | 모의 전송에도 같은 수치 적용; 실서버 제한 동작 검증은 아님 |

배송비·옵션·판매자 근거는 앱의 내부 자료로 유지하며 공식 상품 응답에 임의 필드로 추가하지 않는다. 모의 상품 링크는 사용자가 확인한 실제 상품 페이지 주소를 사용한다. 공식 예제의 제휴 추적 링크 발급이나 HMAC 인증은 이번 실습의 실제 호출 검증 범위가 아니다.
