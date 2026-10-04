import json

import httpx
import pytest

from researchpilot.integrations.ollama import (
    OllamaError,
    OllamaProvider,
    OllamaResponseError,
)

SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}


def test_generate_sends_schema_and_returns_raw_output() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "llama3.2",
                "response": '{"summary":"Useful"}',
                "done": True,
            },
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OllamaProvider(
            client,
            base_url="http://localhost:11434/",
            model="llama3.2",
        )
        raw = provider.generate(
            system_prompt="System",
            prompt="Prompt",
            response_schema=SCHEMA,
        )

    assert provider.provider_name == "ollama"
    assert provider.model_name == "llama3.2"
    assert raw == '{"summary":"Useful"}'
    assert captured == {
        "model": "llama3.2",
        "system": "System",
        "prompt": "Prompt",
        "format": SCHEMA,
        "stream": False,
        "options": {"temperature": 0},
    }


def test_timeout_is_translated_to_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OllamaProvider(client, base_url="http://ollama", model="llama")
        with pytest.raises(OllamaError, match="timed out"):
            provider.generate(
                system_prompt="System",
                prompt="Prompt",
                response_schema=SCHEMA,
            )


def test_unavailable_server_is_translated_to_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OllamaProvider(client, base_url="http://ollama", model="llama")
        with pytest.raises(OllamaError, match="Ollama is unavailable"):
            provider.generate(
                system_prompt="System",
                prompt="Prompt",
                response_schema=SCHEMA,
            )


def test_http_error_includes_ollama_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": "model 'llama' not found"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OllamaProvider(client, base_url="http://ollama", model="llama")
        with pytest.raises(OllamaError, match="model 'llama' not found"):
            provider.generate(
                system_prompt="System",
                prompt="Prompt",
                response_schema=SCHEMA,
            )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"not json", "malformed JSON"),
        (json.dumps([]).encode(), "must be a JSON object"),
        (json.dumps({"done": True}).encode(), "missing generated text"),
        (
            json.dumps({"response": '{"summary":"x"}', "done": False}).encode(),
            "did not finish generation",
        ),
    ],
)
def test_malformed_response_envelopes_are_rejected(
    content: bytes,
    message: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OllamaProvider(client, base_url="http://ollama", model="llama")
        with pytest.raises(OllamaResponseError, match=message):
            provider.generate(
                system_prompt="System",
                prompt="Prompt",
                response_schema=SCHEMA,
            )
