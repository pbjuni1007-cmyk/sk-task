"""요청별 대화와 화면 상태. 사용자별 state 안에서만 사용한다."""

from uuid import uuid4


def conversation(state, request_id=None):
    if request_id is None:
        return state.setdefault("draft_chat", {})
    return state.setdefault("conversations", {}).setdefault(request_id, {})


def reset_execution(chat):
    # 중단된 Agent를 다시 연결하지 않는다. DB 문서와 대화 표시 기록은 보존한다.
    chat.pop("agent", None)
    chat.pop("result", None)


def clear_confirmations(state):
    state.pop("submission", None)
    state.pop("decision", None)
    for chat in [state.get("draft_chat", {}), *state.get("conversations", {}).values()]:
        if chat.get("result", {}).get("pending"):
            reset_execution(chat)


def navigate(state, view, request_id=None):
    clear_confirmations(state)
    state.update(view=view, request_id=request_id)
    state.pop("phase", None)


def new_purchase(state):
    navigate(state, "create")
    state.pop("draft_chat", None)
    state.pop("notice", None)
    state.pop("search_notice", None)
    state["create_id"] = uuid4().hex


def deactivate(state):
    clear_confirmations(state)
    for chat in [state.get("draft_chat", {}), *state.get("conversations", {}).values()]:
        reset_execution(chat)


def sync_version(chat, version):
    if chat.get("version") not in (None, version):
        reset_execution(chat)
    chat["version"] = version
