"""LLM client — OpenAI Chat Completions compatible.

Handles DeepSeek (direct), OpenRouter, AiHubMix, and any other provider that
speaks the OpenAI streaming protocol. For Anthropic native (cache_control,
tool_use content blocks) use ``AnthropicClient`` instead.

Two streaming methods:

- ``stream_chat(messages)`` — text only; yields ``str | UsageDelta``.
- ``stream_chat_with_tools(messages, tools, tool_executor)`` — multi-iteration
  tool-use loop; yields ``str | UsageDelta | ToolCallRequested | ToolCallFulfilled``.

The two are kept separate so callers that don't need tools incur zero protocol
overhead, and existing code that wraps ``stream_chat`` keeps working.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx

from uteki_api.core.config import settings
from uteki_api.llm.usage import ToolCallFulfilled, ToolCallRequested, UsageDelta
from uteki_api.schemas.chat import ChatMessage, ToolCallSpec

# A coroutine the harness gives us so we can execute tools without knowing
# how (sandboxing, audit, budget, etc. all live in the harness).
ToolExecutor = Callable[[str, dict], Awaitable[ToolCallFulfilled]]


class LLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    # ─── plain text streaming ───────────────────────────────────────────
    async def stream_chat(
        self,
        messages: list[ChatMessage],
    ) -> AsyncIterator[str | UsageDelta]:
        """Stream content deltas from an OpenAI-compatible /chat/completions endpoint.

        Yields ``str`` for text deltas, then a single ``UsageDelta`` at the
        natural end of the stream. ``stream_options.include_usage`` asks the
        upstream to include token counts in the final SSE frame (OpenAI 1.0+,
        DeepSeek, and most aggregators support this; harmless if ignored).
        """
        if not self.configured:
            raise RuntimeError(
                "LLM not configured. Set provider credentials or set UTEKI_USE_MOCK_LLM=true."
            )

        async for chunk in self._chat_once(messages, tools=None):
            yield chunk

    # ─── tool-use loop ──────────────────────────────────────────────────
    async def stream_chat_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[dict],
        tool_executor: ToolExecutor,
        max_iterations: int = 8,
    ) -> AsyncIterator[str | UsageDelta | ToolCallRequested | ToolCallFulfilled]:
        """Multi-iteration tool-use loop using OpenAI chat protocol.

        Each iteration:
          1. POST current messages (with ``tools`` + ``tool_choice="auto"``) and
             stream the response.
          2. Yield text deltas as-is.
          3. If the response requested tool calls, yield ``ToolCallRequested``,
             call ``tool_executor``, yield ``ToolCallFulfilled``, and append
             both the assistant message (with ``tool_calls``) and a
             ``role="tool"`` message per result back into ``messages``.
          4. Otherwise (no tool calls), emit accumulated usage and return.

        ``max_iterations`` is a hard ceiling on how many times we re-call the
        model. Beyond that we raise to let the harness mark the run errored.
        """
        if not self.configured:
            raise RuntimeError(
                "LLM not configured. Set provider credentials or set UTEKI_USE_MOCK_LLM=true."
            )

        # Work on a mutable copy; caller's list stays untouched.
        msgs: list[ChatMessage] = list(messages)

        totals: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        }

        for _ in range(max_iterations):
            # Single turn: collect text + tool_calls as we go.
            text_parts: list[str] = []
            tool_calls: dict[int, dict] = {}  # index → partial spec
            usage_payload: dict | None = None
            finish_reason: str | None = None

            async for raw in self._chat_once_raw(msgs, tools=tools):
                kind, payload = raw
                if kind == "delta_content":
                    text_parts.append(payload)
                    yield payload
                elif kind == "delta_tool_calls":
                    # payload is the raw list[dict] from the SSE frame
                    self._merge_tool_call_deltas(tool_calls, payload)
                elif kind == "finish_reason":
                    finish_reason = payload
                elif kind == "usage":
                    usage_payload = payload

            # Accumulate usage across iterations.
            if usage_payload:
                totals["input_tokens"] += int(usage_payload.get("prompt_tokens") or 0)
                totals["output_tokens"] += int(usage_payload.get("completion_tokens") or 0)
                totals["cache_read_tokens"] += int(
                    usage_payload.get("prompt_cache_hit_tokens") or 0
                )

            # No tools requested → final answer; emit usage + return.
            if finish_reason != "tool_calls" or not tool_calls:
                yield UsageDelta(**totals)
                return

            # Convert partial dict → ordered list of ToolCallSpec.
            ordered = self._finalise_tool_calls(tool_calls)
            if not ordered:
                # Model claimed tool_calls but we couldn't parse any — bail.
                yield UsageDelta(**totals)
                return

            # Append the assistant message that requested these tools.
            assistant_msg = ChatMessage(
                role="assistant",
                content="".join(text_parts) or "",
                tool_calls=ordered,
            )
            msgs.append(assistant_msg)

            # Execute each tool sequentially and append role="tool" replies.
            for spec in ordered:
                fn = spec.function or {}
                name = str(fn.get("name") or "")
                args_str = fn.get("arguments") or "{}"
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else dict(args_str)
                except json.JSONDecodeError:
                    args = {}

                yield ToolCallRequested(call_id=spec.id, name=name, arguments=args)

                fulfilled = await tool_executor(name, args)
                # Always carry the requested id back so the LLM can match.
                fulfilled = ToolCallFulfilled(
                    call_id=spec.id,
                    name=fulfilled.name or name,
                    ok=fulfilled.ok,
                    summary=fulfilled.summary,
                    preview=fulfilled.preview,
                    error=fulfilled.error,
                )
                yield fulfilled

                result_body = self._tool_result_body(fulfilled)
                msgs.append(
                    ChatMessage(
                        role="tool",
                        tool_call_id=spec.id,
                        content=result_body,
                    )
                )

        # Hit max_iterations — raise so harness marks run errored.
        raise RuntimeError(f"tool-use loop exceeded max_iterations={max_iterations}")

    # ─── internals ──────────────────────────────────────────────────────

    async def _chat_once(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict] | None,
    ) -> AsyncIterator[str | UsageDelta]:
        """One round-trip; yields text + final UsageDelta (no tool plumbing).

        Used by the public ``stream_chat`` so the legacy text-only path keeps
        its simple surface.
        """
        usage_payload: dict | None = None
        async for kind, payload in self._chat_once_raw(messages, tools=tools):
            if kind == "delta_content":
                yield payload
            elif kind == "usage":
                usage_payload = payload

        if usage_payload is not None:
            yield UsageDelta(
                input_tokens=int(usage_payload.get("prompt_tokens") or 0),
                output_tokens=int(usage_payload.get("completion_tokens") or 0),
                cache_read_tokens=int(usage_payload.get("prompt_cache_hit_tokens") or 0),
                cache_creation_tokens=0,
            )

    async def _chat_once_raw(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict] | None,
    ) -> AsyncIterator[tuple[str, object]]:
        """Single chat-completions roundtrip → emits typed (kind, payload) tuples.

        Kinds:
          ("delta_content", str)         — text token
          ("delta_tool_calls", list)     — raw tool_calls list from this frame
          ("finish_reason", str)         — last seen finish_reason
          ("usage", dict)                — final usage block
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": self.model,
            "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [m.model_dump(exclude_none=True) for m in messages],
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client,
            client.stream("POST", url, json=payload, headers=headers) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue

                u = obj.get("usage")
                if u:
                    yield "usage", u

                choices = obj.get("choices") or []
                if not choices:
                    continue
                ch0 = choices[0]
                delta = ch0.get("delta") or {}
                fr = ch0.get("finish_reason")
                if fr:
                    yield "finish_reason", fr

                content = delta.get("content")
                if content:
                    yield "delta_content", content

                tcs = delta.get("tool_calls")
                if tcs:
                    yield "delta_tool_calls", tcs

    @staticmethod
    def _merge_tool_call_deltas(acc: dict[int, dict], frame: list[dict]) -> None:
        """Merge a single SSE frame's tool_calls deltas into the accumulator.

        OpenAI streams tool_call.function.arguments incrementally across
        frames, keyed by ``index``. Each frame may carry: index, id (once),
        type, function.name (once), function.arguments (incremental).
        """
        for delta in frame:
            idx = delta.get("index", 0)
            slot = acc.setdefault(
                idx,
                {"id": None, "type": "function", "name": None, "arguments": ""},
            )
            if delta.get("id"):
                slot["id"] = delta["id"]
            if delta.get("type"):
                slot["type"] = delta["type"]
            fn = delta.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                # arguments arrives as raw string fragments — concatenate.
                slot["arguments"] += fn["arguments"]

    @staticmethod
    def _finalise_tool_calls(acc: dict[int, dict]) -> list[ToolCallSpec]:
        out: list[ToolCallSpec] = []
        for idx in sorted(acc.keys()):
            slot = acc[idx]
            call_id = slot.get("id") or f"tool_{idx}"
            name = slot.get("name") or ""
            args = slot.get("arguments") or "{}"
            if not name:
                # Garbage frame — drop silently rather than poison the loop.
                continue
            out.append(
                ToolCallSpec(
                    id=call_id,
                    type="function",
                    function={"name": name, "arguments": args},
                )
            )
        return out

    @staticmethod
    def _tool_result_body(f: ToolCallFulfilled) -> str:
        """JSON body the LLM sees as the tool's reply.

        Kept compact and structured so models reliably extract numbers.
        """
        body: dict = {"ok": f.ok}
        if f.summary:
            body["summary"] = f.summary
        if f.preview is not None:
            body["data"] = f.preview
        if f.error:
            body["error"] = f.error
        return json.dumps(body, ensure_ascii=False)
