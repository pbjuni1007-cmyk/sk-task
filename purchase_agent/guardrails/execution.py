"""Budgets cover main calls, summary calls and structured-output repair."""

from time import monotonic
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel, generate_from_stream
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field


class BudgetExceeded(RuntimeError):
    pass


class CallBudget:
    on_event = None

    def emit(self, kind, **data):
        if self.on_event:
            self.on_event({"kind": kind, **data})

    def reset(self):
        self.started = monotonic()
        self.models = 0
        self.tools = 0
        self.repairs = 0
        self.tokens = 0
        self.tool_results = []

    def remaining(self):
        return 60 - (monotonic() - self.started)

    def check(self):
        if self.remaining() <= 0:
            raise BudgetExceeded("TIME_LIMIT")

    def model_call(self):
        self.check()
        if self.models >= 6:
            raise BudgetExceeded("MODEL_LIMIT")
        self.models += 1

    def tool_call(self):
        self.check()
        if self.tools >= 10:
            raise BudgetExceeded("TOOL_LIMIT")
        self.tools += 1

    def repair(self, error):
        self.repairs += 1
        if self.repairs > 1:
            raise BudgetExceeded("OUTPUT_REPAIR_LIMIT")
        return "형식이 잘못되었습니다. 스키마에 맞춰 한 번만 수정하세요."

    def metrics(self):
        return {
            "model_attempts": self.models,
            "tool_attempts": self.tools,
            "tokens": self.tokens,
            "elapsed_seconds": round(monotonic() - self.started, 3),
        }


class BudgetModel(BaseChatModel):
    # 일반 응답·대화 요약·보조 키 재시도 모두 같은 호출 예산을 사용한다.
    inner: Any = Field(exclude=True, repr=False)
    budget: Any = Field(exclude=True, repr=False)
    secondary: Any = Field(default=None, exclude=True, repr=False)

    @property
    def _llm_type(self):
        return "budgeted-model"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(
            update={
                "inner": self.inner.bind_tools(tools, parallel_tool_calls=False, **kwargs),
                "secondary": self.secondary.bind_tools(tools, parallel_tool_calls=False, **kwargs)
                if self.secondary is not None
                else None,
            }
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return generate_from_stream(self._stream(messages, stop=stop, **kwargs))

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        active = (
            self.secondary
            if getattr(self.budget, "secondary_active", False) and self.secondary is not None
            else self.inner
        )
        while True:
            self.budget.model_call()
            self.budget.emit("model_started")
            received = False
            try:
                for chunk in active.stream(
                    messages,
                    stop=stop,
                    timeout=min(20, max(0.1, self.budget.remaining())),
                    **kwargs,
                ):
                    self.budget.check()
                    received = True
                    self.budget.tokens += (chunk.usage_metadata or {}).get("total_tokens", 0)
                    self.budget.emit("model_chunk")
                    if not isinstance(chunk, AIMessageChunk):
                        chunk = AIMessageChunk(**chunk.model_dump(exclude={"type"}))
                    yield ChatGenerationChunk(message=chunk)
                self.budget.check()
                return
            except Exception as error:
                from openai import APIStatusError

                # 일부 응답 뒤 재시도하면 서로 다른 tool-call 조각이 섞일 수 있다.
                if received or not (
                    isinstance(error, APIStatusError)
                    and error.status_code in (401, 403, 429)
                    and active is self.inner
                    and self.secondary is not None
                ):
                    raise
                self.budget.secondary_active = True
                active = self.secondary
                self.budget.emit("model_retry")


class ToolBudgetMiddleware(AgentMiddleware):
    def __init__(self, budget):
        self.budget = budget

    def wrap_tool_call(self, request, handler):
        self.budget.tool_call()
        self.budget.emit("tool_started", tool=request.tool_call["name"])
        result = handler(request)
        import json

        code = None
        try:
            code = json.loads(result.content).get("error_code")
        except (ValueError, TypeError, AttributeError):
            pass
        self.budget.emit("tool_finished", tool=request.tool_call["name"], ok=code is None)
        self.budget.tool_results.append({"tool": request.tool_call["name"], "error_code": code})
        return result
