"""호출자 프로필·소유권·요청 버전 검증. DB 조회와 변경은 서비스 책임이다."""

from ..config import DEMO_PROFILES
from ..errors import BusinessError


def validate_context(context):
    if DEMO_PROFILES.get(context.actor_id) != (
        context.department_id,
        context.role,
    ) or not context.thread_id.startswith(context.actor_id + ":"):
        raise BusinessError("INVALID_CONTEXT")


def validate_access(context, head, ref, *, owner=False, current=False):
    if head["owner"] != context.actor_id and (owner or context.role == "requester"):
        raise BusinessError("FORBIDDEN")
    if current and head["version"] != ref.version:
        raise BusinessError("STALE_VERSION")
