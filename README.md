# SK-TASK

Task Automation for Supplier Knowledge

사내 모니터 구매요청의 상품 비교, 배송비 포함 예산 검토, 문서3종 작성과 직원 제출·담당자 결재를 지원한다. 실제 OpenAI 모델을 사용하며 쿠팡 검색은 사용자 확인 상품2개로 만든 모의 API다. 실제 주문·결제는 하지 않는다.

## 실행

Python3.12.13 / LangChain1.4.0 / langchain-openai1.6.2 / Streamlit1.63.0. 프로젝트 가상환경과 의존성 버전을 고정했다.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

http://127.0.0.1:8501/ 에서 구매 조건 → 상품 비교·선택 → 문서 확인·제출 순서로 사용한다. 상세한 입력 예시는 [시연 가이드](DEMO_GUIDE.md)를 참고한다.

프로젝트 `.env`에 `OPENAI_API_KEY`를 설정한다. 선택적으로 `OPENAI_API_KEY_SUB`를 넣으면 기본 키401/403/429 오류 시 보조 키로 전환한다. 전환 후 같은 Agent 세션은 보조 키를 사용하며 실패 시도도 모델6회 예산에 포함한다. 키는 로그·화면에 출력하지 않는다. 모델은 `PURCHASE_MODEL`로 지정하며 기본값은 gpt-4o-mini다.

## 구현

- 단일 LangChain Agent, 7개 도구, 구조화 출력 및 최대1회 보정.
- 모델6회·도구10회·실행60초 상한. 요약/보조 키 호출도 합산, 종속 도구는 순차 호출.
- 검색만 요청하면 상품 선택·검토·문서 생성을 실행 경계에서도 차단.
- 배송비 포함 총액, 50만원 이상 후보2개, 100만원 이상 구매 담당자→추가 승인자.
- 구매 목적 없이 검색·초안 가능, 목적 누락 상태의 제출 차단.
- 사용자 확인 전 제출 중단. 확인은 현재 사용자·대화·버전·문서에 결속되며 중복 제출 방지.
- SQLite 요청·버전·결재 저장. 변경은 새 버전, 과거 문서 보존, 사용자별 접근 제한.
- 대화별 InMemorySaver와 동의 기반 SQLite Store. 가격/사양 우선 정렬 및 간결/상세 표현 적용.
- 구매요청서·상품 비교표·규정 검토 보고서에 동일 요청/버전/수량/단가/총액 포함.

소스: purchase_agent/{agent,tools,middleware,model,preferences,memory}.py는 Agent 계층, workflow/storage/policy/documents는 업무 계층, ui/app.py는 화면 계층이다. 공통 계약은 schemas.py와 services.py다.

## 검증 · 2026-09-10

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
.venv/bin/python scripts/check_catalog.py --strict
```

전체114개 오프라인 테스트 통과. socket 접속을 차단한 테스트이며 실제 모델 품질과 구분한다. 의존성 충돌 없음, 사용자 확인 상품2개 검사 통과.

사용자 확인 상품 + 실제 gpt-4o-mini: 정상10/10, 성능20/20 성공. p50 6.2695초 / p95 6.922초. docs/evidence/evaluation-acceptance-user-confirmed.json 및 docs/evidence/evaluation-latency-user-confirmed.json에 모델·Python·소스해시·호출·토큰·지연을 기록한다. 마지막 검색-only/표시정렬 보강 전 측정이며 해당 수정 후 전체 성능 재측정은 하지 않았다. 수정본 여러 턴 검색·선택·수량 변경·제출 취소 스모크는 통과했다.

기본 키429 모의 오류→실제 보조 키 응답도 확인했다. 실제 구매/승인 운영 시스템에 연결하지 않았으며 UI 역할은 시연용 프로필이다.

## 범위와 출처

- [상품 자료](fixtures/coupang/README.md): 클라인즈114000원 / LG169000원, 무료·로켓배송은 사용자가 확인한 당시 정보다. 실시간 가격 보장이 아니다.
- API 요청/응답 예제: fixtures/coupang/search-request.json, search-response.json. 내부 배송/출처 메타데이터는 evidence.json으로 분리했다.
- 공식 도움말의 동적 본문 독립 대조는 접근 제한으로 미완료다. 승인된 설계서의 요청/응답 필드 계약을 구현했다. 모의50회/분 제한은 실제 Search API 한도가 아니다.
- [38개 설계 기준 추적표](tests/traceability.md), [Agent 설계서](docs/AGENT_DESIGN.md).

DB는 runtime/purchase.sqlite3. .env/runtime/.venv는 Git 제외 대상이다. macOS ARM64 이외 환경, 운영 인증 및 해상도별 시각 검증은 별도 범위다.
