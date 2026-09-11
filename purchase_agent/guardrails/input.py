"""입력·출력 개인정보 마스킹과 길이 제한."""

import re


def redact(text):
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[이메일]", text)
    text = re.sub(r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)", "[전화번호]", text)
    text = re.sub(r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)", "[식별번호]", text)
    return text[:6000]
