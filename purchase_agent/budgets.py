"""실습용 부서 예산 스냅샷. 실제 회계 잔액이나 지출 예약을 의미하지 않는다."""

DEPARTMENT_BUDGETS = {
    "development": {
        "department_name": "개발팀",
        "remaining_krw": 1200000,
        "per_request_limit_krw": 500000,
    },
    "operations": {
        "department_name": "운영팀",
        "remaining_krw": 800000,
        "per_request_limit_krw": 300000,
    },
    "purchasing": {
        "department_name": "구매팀",
        "remaining_krw": 1000000,
        "per_request_limit_krw": 500000,
    },
    "management": {
        "department_name": "경영지원팀",
        "remaining_krw": 2000000,
        "per_request_limit_krw": 1000000,
    },
}
