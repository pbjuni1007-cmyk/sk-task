"""오프라인 기본 설정. 프로필 선택은 인증이 아닌 데모 기능이다."""

from .schemas import ActorContext

DEMO_PROFILES = {
    "employee_a": ("development", "requester"),
    "employee_b": ("operations", "requester"),
    "buyer_a": ("purchasing", "buyer"),
    "manager_a": ("management", "manager"),
}


def demo_context(profile_id: str, session_id: str) -> ActorContext:
    department, role = DEMO_PROFILES[profile_id]
    return ActorContext(
        actor_id=profile_id,
        department_id=department,
        role=role,
        thread_id=f"{profile_id}:{session_id}",
    )
