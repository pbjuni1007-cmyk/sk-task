# 시연용 DB와 실행 방법

회사 상황을 가정한 **가상 구매 요청 10건**을 `runtime/company-demo.sqlite3`에 준비한다. 현재 테스트 DB를 복사하지 않고, 실제 업무 서비스의 검색·검토·문서 생성·제출·결재 함수를 거쳐 만든다. OpenAI나 실제 주문 API는 호출하지 않는다.

상품은 기존 카탈로그의 확인 당시 가격을 사용한다. 결재 시간은 DB 생성 시각이다. 과거 여러 달의 운영 기록이나 실제 회사 거래를 의미하지 않는다. 부서 예산은 기존 정적 모의 예산이며 요청 누적에 따라 차감되지 않는다.

## 담긴 업무

| 사용자        | 요청                                  |      배송비 포함 금액 | 상태                    |
| ------------- | ------------------------------------- | --------------------: | ----------------------- |
| 박직원·개발팀 | 신규 입사자 2명 모니터 지급           |             338,000원 | 승인                    |
| 김직원·운영팀 | 고객지원 좌석 노후 모니터 교체        |             342,000원 | 승인                    |
| 박직원·개발팀 | 테스트 랩 공용 모니터 6대 확충        |           1,248,600원 | 추가 승인까지 완료      |
| 김직원·운영팀 | 회의실 보조 모니터 추가 구매          |             338,000원 | 유휴 장비 재배치로 반려 |
| 박직원·개발팀 | 프로젝트 투입 인력 보조 모니터 지급   |             507,000원 | 지급 대상자 보완 요청   |
| 박직원·개발팀 | 데이터 분석 담당자 와이드 모니터 교체 |           1,197,000원 | 최승인 추가 승인 대기   |
| 김직원·운영팀 | 장애 대응 관제 좌석 모니터 교체       |             456,000원 | 이담당 검토 대기        |
| 박직원·개발팀 | 하반기 신입 개발자 장비 지급          |             676,000원 | 이담당 검토 대기        |
| 김직원·운영팀 | 재택근무 대여 장비 2세트 준비         |             228,000원 | 문서 작성 완료·제출 전  |
| 박직원·개발팀 | 사내 교육장 실습 좌석 증설 검토       | 미선택·예산 900,000원 | 작성 중                 |

박직원은 내 요청 6건, 김직원은 4건을 볼 수 있다. 이담당의 처리 대기는 2건, 최승인의 처리 대기는 1건이다. 완료함에는 승인·반려 4건이 있다. 요청을 선택하면 문서와 처리 의견도 확인할 수 있다.

## 최초 생성

저장소 루트에서 실행한다. `.venv`가 없는 현재 로컬 환경에서는 아래 `.venv/bin/python`을 `../langchain-practice/.venv/bin/python`으로 바꾼다.

```sh
.venv/bin/python scripts/seed_demo.py --db runtime/company-demo.sqlite3
.venv/bin/python scripts/seed_demo.py --db runtime/practice-empty.sqlite3 --empty
```

이미 존재하는 파일은 덮어쓰지 않는다. 이 PC에는 두 파일을 이미 생성해 두었다. DB 파일은 Git 제외 대상이며, 다른 팀원은 생성 스크립트를 실행하면 된다.

## DB를 골라 실행

실행 중인 서버 터미널에서 `Ctrl+C`로 종료한 뒤 아래 중 하나를 실행한다. 브라우저는 새로고침한다. 같은 포트에 서버 두 개를 동시에 실행할 수 없다.

회사 상황 시연:

```sh
.venv/bin/python scripts/run_app.py --db runtime/company-demo.sqlite3 --port 8503
```

요청 없는 상태에서 AI 흐름 연습:

```sh
.venv/bin/python scripts/run_app.py --db runtime/practice-empty.sqlite3 --port 8503
```

지금까지 사용한 테스트 DB로 돌아가기(현재 PC 전용):

```sh
.venv/bin/python scripts/run_app.py --db /tmp/sk-task-redesign-qa.sqlite3 --port 8503
```

현재 PC에서 기존 API 키 파일을 그대로 사용하는 전체 명령:

```sh
cd /Users/bjpark/skala/lectures/practices/skala-workspace/sk-task-public
../langchain-practice/.venv/bin/python scripts/run_app.py \
  --db runtime/company-demo.sqlite3 --port 8504 \
  --env-file ../langchain-practice/.env
```

이 명령은 기존 8503 서버를 건드리지 않고 `http://127.0.0.1:8504/`에 시연 화면을 연다. 기본 키 파일은 저장소 `.env`이며, `--env-file`로 다른 파일을 지정할 수 있다. DB는 시작할 때 터미널에 절대 경로로 표시한다.

DB를 바꾸면 구매 요청·문서·결재 이력·저장한 선호도가 분리된다. 상품 카탈로그와 정책은 공통이다. 서버 재시작 시 대화와 미확정 확인 창은 초기화되지만 저장된 구매 요청은 유지된다.

## 다음 시연을 처음부터 시작하기

시연하면서 수정한 내용도 해당 DB에 저장된다. `practice-empty` 역시 사용 후에는 비어 있지 않다. 원래 10건 구성이나 빈 상태로 다시 시작하려면 기존 파일 삭제 대신 새 이름으로 생성한다.

```sh
.venv/bin/python scripts/seed_demo.py --db runtime/company-demo-02.sqlite3
.venv/bin/python scripts/run_app.py --db runtime/company-demo-02.sqlite3 --port 8503
```

신규 구매 요청의 AI 시연은 [시연 가이드](DEMO_GUIDE.md)를 따른다. 위 데이터는 업무 배경과 결재함 시연에 사용하며, 미리 생성된 문서만 보여주는 것을 AI 실행 시연으로 대신하지 않는다.
