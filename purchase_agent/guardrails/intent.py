"""모델 인자를 사용자 발화·기존 요청과 대조한다. 불명확한 값은 추측하지 않는다."""

import re
from decimal import Decimal

# 사양(27인치)이나 문서 수(3종)를 구매 수량으로 해석하지 않는다.
QUANTITIES = {
    "한": 1,
    "두": 2,
    "세": 3,
    "네": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
    "스무": 20,
}
QUANTITIES.update({"열" + word: n + 10 for word, n in list(QUANTITIES.items()) if n < 10})
QUANTITY = re.compile(
    r"(?<!\d)("
    + "|".join(sorted(QUANTITIES, key=len, reverse=True))
    + r"|\d+)\s*(?:대|개|명)(?![가-힣]*치)"
)
MONEY = re.compile(
    r"(?<![\d.,])([0-9][0-9,]*(?:\.[0-9]+)?)\s*(억|만|천)?\s*(원|(?<=억)|(?<=만)|(?<=천))"
)


def explicit_numbers(text, known):
    quantity = {int(v) if v.isdigit() else QUANTITIES[v] for v in QUANTITY.findall(text)}
    budget = set()
    for amount, unit, _ in MONEY.findall(text):
        value = (
            Decimal(amount.replace(",", ""))
            * {"": 1, "천": 1000, "만": 10000, "억": 100000000}[unit]
        )
        if value == int(value):
            budget.add(int(value))
    # "수량: 3, 예산: 600000"처럼 단위를 생략한 명시적 필드도 허용한다.
    quantity.update(int(v) for v in re.findall(r"수량\s*[:은는=]?\s*(\d+)(?!\d)", text))
    budget.update(
        int(v.replace(",", ""))
        for v in re.findall(r"예산\s*[:은는=]?\s*([\d,]+)(?![\d,.]|\s*[만천억])", text)
    )
    # 하나만 빠진 상황의 단답. 두 필드가 모두 없으면 단위를 다시 확인한다.
    missing = [key for key in ("quantity", "budget_krw") if not known.get(key)]
    if len(missing) == 1 and re.fullmatch(r"\s*\d[\d,]*\s*", text):
        (quantity if missing[0] == "quantity" else budget).add(int(text.strip().replace(",", "")))
    return {"quantity": quantity, "budget_krw": budget}


def selection_intent(text):
    compact = re.sub(r"\s+", "", text)
    if any(
        word in compact
        for word in (
            "선택하지",
            "선택은하지",
            "고르지",
            "골라주지",
            "선택은내가",
            "내가선택",
            "후보만",
            "검색만",
            "찾기만",
        )
    ):
        return False
    if re.search(r"선택(?:해|하|할)|골라|고르", compact):
        return True
    extreme = any(
        word in compact for word in ("제일비싼", "가장비싼", "제일싼", "가장싼", "최저가", "최고가")
    )
    if extreme and any(word in compact for word in ("걸로", "것으로", "문서", "요청서", "작성")):
        return True
    return None


def validate_values(session, values, known):
    for key in ("quantity", "budget_krw"):
        if key not in values:
            continue
        supplied = session.explicit_inputs.get(key, set())
        if supplied:
            if values[key] not in supplied:
                return (
                    "UNCONFIRMED_INPUT: 사용자가 말한 수량·예산만 사용하고 불명확하면 질문하세요."
                )
        elif values[key] != known.get(key):
            return "UNCONFIRMED_INPUT: 누락된 수량·예산을 추측하지 말고 사용자에게 질문하세요."
    return None
