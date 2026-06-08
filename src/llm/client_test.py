
import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from pytest import MonkeyPatch

from src.llm.client import ChatCompletionsApiClient, OpenAIResponder, ResponsesApiClient
from src.models import AssistantApiMode, ResolvedAssistant
from src.service.response_service import StreamEvent


@dataclass(frozen=True)
class FakeOpenAIEvent:
    type: str = ""
    delta: str = ""
    text: str = ""
    choices: list[Any] | None = None


class ClosableAsyncStream:
    def __init__(self, events: list[FakeOpenAIEvent]) -> None:
        self.events = events
        self.index = 0
        self.closed = False

    def __aiter__(self) -> "ClosableAsyncStream":
        return self

    async def __anext__(self) -> FakeOpenAIEvent:
        if self.index >= len(self.events):
            raise StopAsyncIteration
        event = self.events[self.index]
        self.index += 1
        return event

    async def aclose(self) -> None:
        self.closed = True


def test_responses_stream_yields_reasoning_and_visible_output_text(
    monkeypatch: MonkeyPatch,
) -> None:
    # 観点: Responses APIのreasoningと本文を別々の内部イベントとして取り出すこと。
    # 目的: provider固有eventをUIのkind別表示契約へ変換する境界を固定する。
    async def fake_events() -> AsyncIterator[FakeOpenAIEvent]:
        yield FakeOpenAIEvent(type="response.reasoning_summary_text.delta", delta="hidden")
        yield FakeOpenAIEvent(type="response.output_text.delta", delta="visible")

    class FakeResponses:
        async def create(self, **_: object) -> AsyncIterator[FakeOpenAIEvent]:
            return fake_events()

    class FakeClient:
        responses = FakeResponses()

    def fake_async_openai(**_: object) -> FakeClient:
        return FakeClient()

    monkeypatch.setattr("src.llm.client.AsyncOpenAI", fake_async_openai)

    events = asyncio.run(
        _collect(
            ResolvedAssistant(
                id="responses",
                name="Responses",
                description="",
                system_prompt="",
                user_prompts=[],
                api_mode="responses",
                base_url=None,
                config={"api_key": "test", "model": "test-model"},
                max_history_messages=40,
            )
        )
    )

    assert events == [
        StreamEvent("reasoning_delta", reasoning_delta="hidden"),
        StreamEvent("delta", delta="visible"),
    ]


def test_responses_stream_closes_provider_stream_when_consumer_stops(
    monkeypatch: MonkeyPatch,
) -> None:
    # 観点: Responses APIの途中で上位taskが止まるとprovider streamを閉じること。
    # 目的: AIプロバイダ側HTTPストリームが生成継続したまま残らないようにする。
    provider_stream = ClosableAsyncStream(
        [FakeOpenAIEvent(type="response.output_text.delta", delta="first")]
    )

    class FakeResponses:
        async def create(self, **_: object) -> ClosableAsyncStream:
            return provider_stream

    class FakeClient:
        responses = FakeResponses()

        async def close(self) -> None:
            return None

    def fake_async_openai(**_: object) -> FakeClient:
        return FakeClient()

    monkeypatch.setattr("src.llm.client.AsyncOpenAI", fake_async_openai)

    async def stop_after_first_event() -> None:
        stream = OpenAIResponder().stream(
            messages=[{"role": "user", "content": "hello"}],
            assistant=_assistant("responses"),
        )
        assert await anext(stream) == StreamEvent("delta", delta="first")
        await stream.aclose()

    asyncio.run(stop_after_first_event())

    assert provider_stream.closed is True


def test_chat_completions_stream_yields_reasoning_and_choice_delta_content(
    monkeypatch: MonkeyPatch,
) -> None:
    # 観点: Chat Completions APIのreasoning_contentとcontentを別々に扱うこと。
    # 目的: reasoningを通常本文へ混ぜず、専用kindとして流す変換ルールを固定する。
    async def fake_events() -> AsyncIterator[FakeOpenAIEvent]:
        hidden = SimpleNamespace(content=None, reasoning_content="hidden")
        visible = SimpleNamespace(content="answer")
        yield FakeOpenAIEvent(choices=[SimpleNamespace(delta=hidden)])
        yield FakeOpenAIEvent(choices=[SimpleNamespace(delta=visible)])

    class FakeCompletions:
        async def create(self, **_: object) -> AsyncIterator[FakeOpenAIEvent]:
            return fake_events()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    def fake_async_openai(**_: object) -> FakeClient:
        return FakeClient()

    monkeypatch.setattr("src.llm.client.AsyncOpenAI", fake_async_openai)

    events = asyncio.run(
        _collect(
            ResolvedAssistant(
                id="chat",
                name="Chat",
                description="",
                system_prompt="",
                user_prompts=[],
                api_mode="chat_completions",
                base_url=None,
                config={"api_key": "test", "model": "test-model"},
                max_history_messages=40,
            )
        )
    )

    assert events == [
        StreamEvent("reasoning_delta", reasoning_delta="hidden"),
        StreamEvent("delta", delta="answer"),
    ]


def test_chat_completions_stream_closes_provider_stream_when_consumer_stops(
    monkeypatch: MonkeyPatch,
) -> None:
    # 観点: Chat Completionsの途中で上位taskが止まるとprovider streamを閉じること。
    # 目的: OpenAI互換APIへのHTTP接続をPython側で明示的にabortする。
    provider_stream = ClosableAsyncStream(
        [FakeOpenAIEvent(choices=[SimpleNamespace(delta=SimpleNamespace(content="first"))])]
    )

    class FakeCompletions:
        async def create(self, **_: object) -> ClosableAsyncStream:
            return provider_stream

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

        async def close(self) -> None:
            return None

    def fake_async_openai(**_: object) -> FakeClient:
        return FakeClient()

    monkeypatch.setattr("src.llm.client.AsyncOpenAI", fake_async_openai)

    async def stop_after_first_event() -> None:
        stream = OpenAIResponder().stream(
            messages=[{"role": "user", "content": "hello"}],
            assistant=_assistant("chat_completions"),
        )
        assert await anext(stream) == StreamEvent("delta", delta="first")
        await stream.aclose()

    asyncio.run(stop_after_first_event())

    assert provider_stream.closed is True


def test_responses_stream_reads_reasoning_text_field(
    monkeypatch: MonkeyPatch,
) -> None:
    # 観点: Responses APIのreasoning delta本文がdelta以外の属性でも取り出せること。
    # 目的: SDKや互換APIごとのreasoningフィールド差分で表示を落とさない。
    async def fake_events() -> AsyncIterator[FakeOpenAIEvent]:
        yield FakeOpenAIEvent(type="response.reasoning_text.delta", text="thinking")

    class FakeResponses:
        async def create(self, **_: object) -> AsyncIterator[FakeOpenAIEvent]:
            return fake_events()

    class FakeClient:
        responses = FakeResponses()

    def fake_async_openai(**_: object) -> FakeClient:
        return FakeClient()

    monkeypatch.setattr("src.llm.client.AsyncOpenAI", fake_async_openai)

    events = asyncio.run(
        _collect(
            ResolvedAssistant(
                id="responses",
                name="Responses",
                description="",
                system_prompt="",
                user_prompts=[],
                api_mode="responses",
                base_url=None,
                config={"api_key": "test", "model": "test-model"},
                max_history_messages=40,
            )
        )
    )

    assert events == [StreamEvent("reasoning_delta", reasoning_delta="thinking")]


def test_chat_completions_stream_reads_reasoning_field_variants(
    monkeypatch: MonkeyPatch,
) -> None:
    # 観点: Chat Completions互換APIのreasoning/thinking系フィールドを拾うこと。
    # 目的: reasoning_content以外を返すモデルでもthinking表示へ流せるようにする。
    async def fake_events() -> AsyncIterator[FakeOpenAIEvent]:
        yield FakeOpenAIEvent(
            choices=[SimpleNamespace(delta=SimpleNamespace(reasoning="reasoning"))]
        )
        yield FakeOpenAIEvent(
            choices=[SimpleNamespace(delta=SimpleNamespace(thinking="thinking"))]
        )

    class FakeCompletions:
        async def create(self, **_: object) -> AsyncIterator[FakeOpenAIEvent]:
            return fake_events()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    def fake_async_openai(**_: object) -> FakeClient:
        return FakeClient()

    monkeypatch.setattr("src.llm.client.AsyncOpenAI", fake_async_openai)

    events = asyncio.run(
        _collect(
            ResolvedAssistant(
                id="chat",
                name="Chat",
                description="",
                system_prompt="",
                user_prompts=[],
                api_mode="chat_completions",
                base_url=None,
                config={"api_key": "test", "model": "test-model"},
                max_history_messages=40,
            )
        )
    )

    assert events == [
        StreamEvent("reasoning_delta", reasoning_delta="reasoning"),
        StreamEvent("reasoning_delta", reasoning_delta="thinking"),
    ]


def test_internal_assistant_options_are_not_sent_to_openai(
    monkeypatch: MonkeyPatch,
) -> None:
    # 観点: アプリ内部だけで使うassistant設定をOpenAI APIのextra_bodyへ送らないこと。
    # 目的: 設定ファイルの内部制御値と外部APIパラメータの境界を固定する。
    captured_kwargs: dict[str, Any] = {}

    async def fake_events() -> AsyncIterator[FakeOpenAIEvent]:
        yield FakeOpenAIEvent(type="response.output_text.delta", delta="ok")

    class FakeResponses:
        async def create(self, **kwargs: object) -> AsyncIterator[FakeOpenAIEvent]:
            captured_kwargs.update(kwargs)
            return fake_events()

    class FakeClient:
        responses = FakeResponses()

    def fake_async_openai(**_: object) -> FakeClient:
        return FakeClient()

    monkeypatch.setattr("src.llm.client.AsyncOpenAI", fake_async_openai)

    asyncio.run(
        _collect(
            ResolvedAssistant(
                id="responses",
                name="Responses",
                description="",
                system_prompt="",
                user_prompts=[],
                api_mode="responses",
                base_url=None,
                config={
                    "api_key": "test",
                    "model": "test-model",
                    "max_history_messages": 2,
                    "allow_file_upload": True,
                    "temperature": 0.2,
                },
                max_history_messages=40,
            )
        )
    )

    assert captured_kwargs["extra_body"] == {"temperature": 0.2}


def test_responses_api_client_builds_responses_request() -> None:
    # 観点: Responses APIクラスがinput/max_output_tokensのrequest形を持つこと。
    # 目的: api_mode分岐ではなくAPI別クラスへrequest構築責務を寄せる。
    request = ResponsesApiClient().build_request(
        model="test-model",
        messages=[{"role": "user", "content": "hello"}],
        config={"temperature": 0.2},
        max_tokens=123,
    )

    assert request == {
        "model": "test-model",
        "input": [{"role": "user", "content": "hello"}],
        "stream": True,
        "store": False,
        "extra_body": {"temperature": 0.2},
        "max_output_tokens": 123,
    }


def test_chat_completions_api_client_builds_chat_request() -> None:
    # 観点: Chat Completions APIクラスがmessages/max_tokensのrequest形を持つこと。
    # 目的: APIごとのリクエスト差分をOpenAIResponderの条件分岐から外へ出す。
    request = ChatCompletionsApiClient().build_request(
        model="test-model",
        messages=[{"role": "user", "content": "hello"}],
        config={"temperature": 0.3},
        max_tokens=456,
    )

    assert request == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
        "extra_body": {"temperature": 0.3},
        "max_tokens": 456,
    }


async def _collect(assistant: ResolvedAssistant) -> list[StreamEvent]:
    return [
        event
        async for event in OpenAIResponder().stream(
            messages=[{"role": "user", "content": "hello"}],
            assistant=assistant,
        )
    ]


def _assistant(api_mode: AssistantApiMode) -> ResolvedAssistant:
    return ResolvedAssistant(
        id=api_mode,
        name=api_mode,
        description="",
        system_prompt="",
        user_prompts=[],
        api_mode=api_mode,
        base_url=None,
        config={"api_key": "test", "model": "test-model"},
        max_history_messages=40,
    )
