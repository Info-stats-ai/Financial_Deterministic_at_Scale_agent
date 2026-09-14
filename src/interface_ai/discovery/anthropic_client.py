"""Anthropic GA computer-toolset adapter."""

from __future__ import annotations

from typing import Any, cast

from anthropic import AsyncAnthropic

from interface_ai.discovery.models import ModelTurn, ToolCall

COMPLETION_TOOL = {
    "name": "complete_capability",
    "description": (
        "Call only after the requested UI goal is visibly complete. Report exact visible "
        "output values and text that proves success."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "final_checkpoint_text": {"type": "string"},
            "outputs": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["summary", "final_checkpoint_text", "outputs"],
    },
}


class ClaudeComputerClient:
    def __init__(
        self,
        *,
        model: str = "claude-sonnet-5",
        max_tokens: int = 2_048,
        client: AsyncAnthropic | None = None,
    ) -> None:
        self.client = client or AsyncAnthropic()
        self.model = model
        self.max_tokens = max_tokens
        self.tools: list[dict[str, Any]] = [
            {
                "type": "computer_toolset_20260801",
                "configs": {"zoom": {"enabled": False}},
            },
            COMPLETION_TOOL,
        ]

    async def next_turn(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
    ) -> ModelTurn:
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            tools=cast(Any, self.tools),
            messages=cast(Any, messages),
        )
        raw_content = [
            block.model_dump(mode="json", exclude_none=True) for block in response.content
        ]
        text: list[str] = []
        calls: list[ToolCall] = []
        for block in raw_content:
            if block["type"] == "text":
                text.append(str(block["text"]))
            elif block["type"] == "tool_use":
                calls.append(
                    ToolCall(
                        id=str(block["id"]),
                        name=str(block["name"]),
                        input=dict(block.get("input", {})),
                        toolset_name=block.get("toolset_name"),
                    )
                )
        return ModelTurn(
            text=text,
            tool_calls=calls,
            raw_content=raw_content,
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
