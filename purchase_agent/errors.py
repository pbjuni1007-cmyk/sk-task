"""업무 서비스와 보호 계층이 공유하는 오류. 외부 응답에 비밀 값을 담지 않는다."""


class BusinessError(Exception):
    pass
