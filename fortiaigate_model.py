"""Strands Agents model provider that routes requests through FortiAIGate.

FortiAIGate exposes a custom, non-streaming endpoint that loosely follows the
OpenAI Responses API shape (input/output arrays) but does not implement SSE
streaming or the standard /v1/responses path, so it cannot use Strands'
built-in OpenAIResponsesModel. This provider makes a single synchronous
request per turn and replays it as a one-shot "stream" of events, which is
all the Strands event loop requires.

Tool calling: the gateway can return a `function_call` output item (the model
deciding to call a tool), but rejects every shape of `function_call_output`
input tested (400/500 regardless of field names or previous_response_id
chaining) -- it cannot complete a normal agentic tool round trip. So when a
tool call is requested and a `tool_executor` is provided, this provider
executes the tool itself and returns the raw result as the assistant's text,
rather than trying to send the result back to FortiAIGate for a second,
synthesized reply.
"""

import json
from collections.abc import AsyncGenerator, Callable
from typing import Any

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from strands.models.model import Model
from strands.types.content import Messages
from strands.types.tools import ToolSpec

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

ToolExecutor = Callable[[str, dict[str, Any]], str]


class FortiAIGateModel(Model):
    """Model provider that calls a FortiAIGate chat endpoint."""

    def __init__(
        self,
        url: str,
        api_key: str,
        model_id: str,
        verify_tls: bool = False,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.verify_tls = verify_tls
        self.tool_executor = tool_executor
        self.config: dict[str, Any] = {"model_id": model_id}

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> Any:
        return self.config

    async def structured_output(
        self, output_model, prompt: Messages, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        raise NotImplementedError("Structured output is not supported by the FortiAIGate demo model")
        yield {}  # pragma: no cover - makes this an async generator

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        input_items = self._format_messages(messages, system_prompt)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: dict[str, Any] = {"model": self.config["model_id"], "input": input_items}
        if tool_specs:
            payload["tools"] = [self._format_tool_spec(spec) for spec in tool_specs]
            payload["tool_choice"] = "auto"

        response = requests.post(
            self.url, headers=headers, json=payload, verify=self.verify_tls, timeout=60
        )
        response.raise_for_status()
        data = response.json()

        function_call = self._extract_function_call(data)
        if function_call and self.tool_executor:
            text = self._execute_and_format(function_call)
        else:
            text = self._extract_text(data)

        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}
        yield {"contentBlockDelta": {"delta": {"text": text}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}

    def _execute_and_format(self, function_call: dict[str, Any]) -> str:
        name = function_call["name"]
        try:
            arguments = json.loads(function_call.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}

        try:
            result = self.tool_executor(name, arguments)
        except Exception as exc:  # noqa: BLE001 - surface any tool failure in the demo UI
            result = f"(tool execution failed: {exc})"

        return f"🔧 Called tool `{name}`({json.dumps(arguments)}) → {result}"

    @staticmethod
    def _format_tool_spec(spec: ToolSpec) -> dict[str, Any]:
        return {
            "type": "function",
            "name": spec["name"],
            "description": spec.get("description", ""),
            "parameters": spec["inputSchema"]["json"],
        }

    @staticmethod
    def _format_messages(messages: Messages, system_prompt: str | None) -> list[dict[str, str]]:
        input_items: list[dict[str, str]] = []
        if system_prompt:
            input_items.append({"role": "system", "content": system_prompt})

        for message in messages:
            text = "".join(block.get("text", "") for block in message["content"] if "text" in block)
            if text:
                input_items.append({"role": message["role"], "content": text})

        return input_items

    @staticmethod
    def _extract_function_call(data: dict[str, Any]) -> dict[str, Any] | None:
        for item in data.get("output", []):
            if item.get("type") == "function_call":
                return item
        return None

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        for item in data.get("output", []):
            if item.get("type") == "message":
                texts = [c.get("text", "") for c in item.get("content", []) if c.get("type") == "output_text"]
                if texts:
                    return "\n".join(texts)
        return "(FortiAIGate returned no message content)"
