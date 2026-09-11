# SK-TASK 문서 목차

처음 실행하려면 [프로젝트 README](../README.md), 발표하려면 [화면 시연 가이드](guides/DEMO_GUIDE.md), 코드를 수정하려면 [개발 안내](guides/DEVELOPMENT.md)부터 읽는다.

## 문서 트리

```text
docs/
├── README.md                         # 문서 진입점·최신 검증 상태
├── AGENT_DESIGN.md                   # 제출용 설계서
├── guides/
│   ├── DEMO_GUIDE.md                 # 실제 화면 시연 순서
│   ├── DEVELOPMENT.md                # 개발·검사·모델 평가 명령
│   └── AGENT_FLOW.md                 # Agent 호출 흐름과 코드 읽기
├── reference/
│   ├── COUPANG_API_CONTRACT_CHECK.md # 공식 API 계약 대조
│   └── COUPANG_FIXTURES.md           # 상품 출처와 가격·배송 조건
├── validation/
│   ├── TEST_TRACEABILITY.md          # 설계 38개와 테스트 근거 연결
│   └── BROWSER_QA_REPORT.md          # 날짜가 고정된 과거 화면 검증
└── evidence/                         # 당시 관찰·측정 원본 JSON
```

## 목적별 안내

| 목적                                 | 문서                                                     |
| ------------------------------------ | -------------------------------------------------------- |
| 발표 화면을 그대로 따라가기          | [실제 화면 시연 순서](guides/DEMO_GUIDE.md)              |
| 개발 환경·린트·포맷·테스트           | [개발 안내](guides/DEVELOPMENT.md)                       |
| Agent 구조 이해                      | [코드 흐름 안내](guides/AGENT_FLOW.md)                   |
| 제출 양식과 설계 판단 확인           | [Agent 설계서](AGENT_DESIGN.md)                          |
| API 요청·응답 계약 확인              | [쿠팡 API 대조](reference/COUPANG_API_CONTRACT_CHECK.md) |
| 상품 근거 확인                       | [상품 자료](reference/COUPANG_FIXTURES.md)               |
| 설계 테스트의 근거 찾기              | [테스트 추적표](validation/TEST_TRACEABILITY.md)         |
| 실제 화면에서 무엇을 검증했는지 확인 | [브라우저 검증 기록](validation/BROWSER_QA_REPORT.md)    |
| 측정·관찰 원문 확인                  | [검증 원본](evidence/)                                   |

## 현재 검증 상태

- 확인일: 2026-09-11. 코드 기준 `381013b`의 로컬 검사 결과다.
- 자동 테스트 **117개 통과**, Ruff 린트·포맷 및 Prettier 검사 통과.
- PR #3(새 구매요청 AI 상태 초기화), #4(동일 조건 재검토 문서 보존)를 포함한다.
- 실제 모델 성능과 브라우저 검증은 [2026-09-10 기록](validation/BROWSER_QA_REPORT.md)을 참고한다. 이후 코드에 대한 전체 브라우저 재검증 결과로 해석하지 않는다.
- 브라우저 다운로드의 실제 저장 완료는 과거 검증에서 미확인이다. 현재 CI 실행 성공 여부는 위 로컬 결과와 별개다.

## 문서 관리 기준

현재 자동 검사 수치는 이 페이지에서 관리한다. 과거 보고서의 날짜·수치와 원본 JSON은 당시 근거로 보존한다. 테스트 추적표는 “어떤 코드가 검증하는가”, 브라우저 보고서는 “당시 화면에서 무엇을 관찰했는가”를 담당한다.

시연 절차는 시연 가이드, 개발 명령은 개발 안내, 상품 조건은 상품 자료, API 필드는 API 대조 문서를 기준으로 한다. 다른 문서는 필요한 요약과 링크를 둔다. 별도 설명이 없는 실행 명령은 저장소 루트 기준이다.
