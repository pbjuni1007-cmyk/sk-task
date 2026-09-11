# SK-TASK

회사 상황을 담은 DB 구성과 전환 실행법은 [시연용 DB 안내](docs/guides/DEMO_DATABASE.md)를 참고한다.

Task Automation for Supplier Knowledge

[7반 6조 제출용 최종 설계서](docs/submission/7반_6조_SK-TASK.md)

사내 모니터 구매요청의 상품 비교, 배송비 포함 예산 검토, 문서3종 작성과 직원 제출·담당자 결재를 지원한다. 실제 OpenAI 모델을 사용하며 쿠팡 검색은 사용자 확인 상품12개로 만든 모의 API다. 실제 주문·결제는 하지 않는다.

## 실행

Python3.12.13 / LangChain1.4.0 / langchain-openai1.6.2 / Streamlit1.63.0. 프로젝트 가상환경과 의존성 버전을 고정했다.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

http://127.0.0.1:8501/ 에서 구매 조건 → 상품 비교·선택 → 문서 확인·제출 순서로 사용한다. 상세한 입력 예시는 [시연 가이드](docs/guides/DEMO_GUIDE.md)를 참고한다.

프로젝트 `.env`에 `OPENAI_API_KEY`를 설정한다. 선택적으로 `OPENAI_API_KEY_SUB`를 넣으면 기본 키401/403/429 오류 시 보조 키로 전환한다. 전환 후 같은 Agent 세션은 보조 키를 사용하며 실패 시도도 모델6회 예산에 포함한다. 키는 로그·화면에 출력하지 않는다. 모델은 `PURCHASE_MODEL`로 지정하며 기본값은 gpt-4o-mini다.

## 구현

- 단일 LangChain Agent, 8개 도구, 구조화 출력 및 최대1회 보정.
- 모델6회·도구10회·실행60초 상한. 요약/보조 키 호출도 합산, 종속 도구는 순차 호출.
- 검색만 요청하면 상품 선택·검토·문서 생성을 실행 경계에서도 차단.
- 배송비 포함 총액, 50만원 이상 후보2개, 100만원 이상 구매 담당자→추가 승인자.
- 구매 목적 없이 검색·초안 가능, 목적 누락 상태의 제출 차단.
- 사용자 확인 전 제출 중단. 확인은 현재 사용자·대화·버전·문서에 결속되며 중복 제출 방지.
- SQLite 요청·버전·결재 저장. 변경은 새 버전, 과거 문서 보존, 사용자별 접근 제한.
- 대화별 InMemorySaver와 동의 기반 SQLite Store. 가격/사양 우선 정렬 및 간결/상세 표현 적용.
- 구매요청서·상품 비교표·규정 검토 보고서에 동일 요청/버전/수량/단가/총액 포함.

소스: purchase_agent/{agent,tools,model,preferences,memory}.py는 Agent 계층, workflow/storage/policy/documents는 업무 계층, ui/app.py는 화면 계층이다. 공통 계약은 schemas.py와 services.py다.

## 검증

최신 자동 검사 결과는 [문서 목차의 검증 상태](docs/README.md#현재-검증-상태)를 확인한다. 검사 실행법은 [개발 안내](docs/guides/DEVELOPMENT.md)에 모았다.

실제 모델·브라우저 실험은 [날짜별 검증 보고서](docs/validation/BROWSER_QA_REPORT.md)에 보관한다. 해당 기록은 현재 코드 전체를 다시 브라우저 검증했다는 뜻이 아니다. 실제 쿠팡 API 호출과 운영 결재 시스템 연결은 실습 범위에 포함하지 않는다.

## 범위와 출처

- [상품 자료](docs/reference/COUPANG_FIXTURES.md): 클라인즈114000원 / LG169000원, 무료·로켓배송은 사용자가 확인한 당시 정보다. 실시간 가격 보장이 아니다.
- API 요청/응답 예제: fixtures/coupang/search-request.json, search-response.json. 내부 배송/출처 메타데이터는 evidence.json으로 분리했다.
- [공식 API 본문 대조](docs/reference/COUPANG_API_CONTRACT_CHECK.md): 2026-09-10 브라우저에서 v1 검색 API 요청·응답 필드, 최대10개·분당50회를 확인했다. 실제 쿠팡 API 인증·호출 검증은 수행하지 않았다.
- [38개 설계 기준 추적표](docs/validation/TEST_TRACEABILITY.md), [Agent 설계서](docs/AGENT_DESIGN.md).

DB는 runtime/purchase.sqlite3. .env/runtime/.venv는 Git 제외 대상이다. macOS ARM64 이외 환경, 운영 인증 및 해상도별 시각 검증은 별도 범위다.

전체 문서는 [문서 목차](docs/README.md)에서 확인할 수 있다.

## 코드 읽기와 개발

[Agent 흐름 안내](docs/guides/AGENT_FLOW.md) 순서로 코드를 읽을 수 있다. 린트·포맷 설정과 `make check` 실행 방법은 [개발 도구 안내](docs/guides/DEVELOPMENT.md)를 참고한다.

## 예산 없는 상품 탐색과 가드레일

예산이 없어도 카탈로그를 먼저 검색하고 수량·목적을 대화에 보관한다. “우리 팀 예산”을 요청하면 소속 부서의 **실습용 모의 예산**을 적용한다. 정식 구매요청은 수량과 예산이 갖춰진 뒤 저장한다. 예산은 정적 자료이며 제출 시 잔액을 차감하지 않는다.

실행 중에는 모델 판단·상품 검색·문서 생성 단계를 실시간으로 표시하고, 최종 답변은 서버 상태를 검증한 뒤 보여준다. 검증 전 모델 원문을 실시간으로 노출하지 않는다.

입력·출력·실행 한도·도구 노출·접근 권한·제출 확인 검사는 `purchase_agent/guardrails/`에 모았다. [가드레일 구조와 읽기 순서](docs/guides/AGENT_FLOW.md#가드레일-모듈)를 참고한다.
