# 개발 도구

Python 코드는 Ruff로 린트와 포맷을 검사한다. Markdown·JSON·YAML 등은 Prettier로 정리한다. Node.js는 문서 포맷 도구에만 필요하며 앱 실행에는 사용하지 않는다.

Agent 구조를 처음 읽는다면 [코드 흐름 안내](AGENT_FLOW.md)를 먼저 본다.

## 설치

저장소 루트에서 Python 3.12와 Node.js 24 환경을 사용한다.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
npm ci --ignore-scripts --no-audit --no-fund
```

Ruff 버전은 `requirements-dev.txt`와 `pyproject.toml`, Prettier 버전은 `package.json`과 `package-lock.json`으로 고정한다.

## 작업 순서

```sh
make format       # Python과 문서 형식 정리
make check        # 린트 + 포맷 검사 + 오프라인 전체 테스트
```

개별 검사와 import 정리가 필요할 때:

```sh
make lint
make format-check
make test
.venv/bin/python -m ruff check . --fix
```

Ruff의 자동 수정 후에는 테스트를 실행한다. pytest가 import로 발견하는 공통 fixture는 `catalog as catalog`처럼 명시적으로 재노출해 미사용 import로 삭제되지 않게 한다. 자동 수정의 `--unsafe-fixes`는 기본 작업 명령에 포함하지 않는다.

다른 가상환경은 `make check PYTHON=/path/to/venv/bin/python`으로 지정한다. 각 도구는 `pyproject.toml`, `.prettierrc.json`, `.prettierignore`를 사용한다. PR 및 main 푸시 시 GitHub Actions가 동일한 검사를 실행하도록 설정되어 있다.

## 변경 범위

- Ruff: Python 문법·미정의 이름·미사용 import·import 순서를 검사하고 한 줄에 붙은 문장을 펼친다.
- Prettier: 문서와 설정 파일을 포맷한다. `docs/evidence/`, `fixtures/`의 원본 자료와 `runtime/`은 제외한다.
- `make format`은 업무 계산, 모델 프롬프트 또는 API 계약을 바꾸기 위한 명령이 아니다. diff와 테스트 결과를 확인한다.
- 현재 별도의 타입 검사기는 설정하지 않는다. Ruff 검사 통과를 타입 검사 통과로 해석하지 않는다.

설정 근거: [Ruff 공식 설정 문서](https://docs.astral.sh/ruff/configuration/), [Prettier 공식 설치 안내](https://prettier.io/docs/install).

## 실제 모델 평가

아래 명령은 실제 모델을 호출하므로 비용이 발생한다. 일반 `make check`와 별개이며 결과는 실행 당시 환경과 입력 기준으로 해석한다.

```sh
.venv/bin/python scripts/evaluate_dialogues.py
.venv/bin/python scripts/evaluate.py --suite acceptance --runs 10 --catalog user-confirmed
.venv/bin/python scripts/evaluate.py --suite latency --runs 20 --catalog user-confirmed
```

과거 실행 결과는 [브라우저 검증 보고서](../validation/BROWSER_QA_REPORT.md)와 [원본 자료](../evidence/)에서 확인한다.
