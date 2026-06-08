
"""OpenAI互換LLM APIとの接続を担当する。

このファイルは OpenAI SDK の event object や APIモード差分を受け止め、
アプリ内部には response_service.StreamEvent だけを返す境界である。HTTP、DB、
テンプレートの責務は持たない。
"""

import logging
from inspect import isawaitable
from collections.abc import AsyncGenerator, AsyncIterable, Mapping
from dataclasses import dataclass
from typing import Protocol, TypeGuard

from openai import AsyncOpenAI

from ..models import AssistantGenerationConfig, LlmMessage, ResolvedAssistant
from ..service.response_service import StreamEvent

logger = logging.getLogger(__name__)

INTERNAL_RUNTIME_CONFIG_KEYS = {
    "max_history_messages",
    "allow_file_upload",
    "allowed_file_extensions",
}


LlmRequestValue = (
    str
    | int
    | float
    | bool
    | list[LlmMessage]
    | AssistantGenerationConfig
)
LlmRequest = dict[str, LlmRequestValue]


class OpenAISdkClient(Protocol):
    """OpenAI SDK呼び出しをAPI mode別の細いメソッドへ隠す。"""

    def create_responses_stream(
        self,
        *,
        model: str,
        input: list[LlmMessage],
        extra_body: AssistantGenerationConfig,
        max_output_tokens: int | None,
    ) -> AsyncGenerator[object]:
        """Responses APIのstreamを作成する。"""
        ...

    def create_chat_completions_stream(
        self,
        *,
        model: str,
        messages: list[LlmMessage],
        extra_body: AssistantGenerationConfig,
        max_tokens: int | None,
    ) -> AsyncGenerator[object]:
        """Chat Completions APIのstreamを作成する。"""
        ...

class OpenAIStreamClient(Protocol):
    """API mode別LLM clientの共通インターフェースを定義する。

    実装クラスはOpenAI互換APIのrequest構築とevent変換を持ち、
    `OpenAIResponder` はAPI mode選択とSDK client寿命だけを扱う。
    """

    api_mode: str

    def build_request(
        self,
        *,
        model: str,
        messages: list[LlmMessage],
        config: AssistantGenerationConfig,
        max_tokens: int | float | str | bool | None,
    ) -> LlmRequest:
        """SDKへ渡すrequest辞書を構築する。"""
        ...

    def stream_events(
        self,
        *,
        client: OpenAISdkClient,
        request: LlmRequest,
    ) -> AsyncGenerator[StreamEvent]:
        """SDK streamから内部StreamEventをyieldする。"""
        ...


@dataclass(frozen=True)
class RuntimeRequestConfig:
    """ResolvedAssistant.configから取り出したLLM実行設定を表す。

    Attributes:
        api_key: OpenAI SDK client生成にだけ使うAPI key。
        model: APIへ送るモデル名。
        options: API固有requestのextra_bodyへ渡す生成オプション。
        max_tokens: API mode別のtoken上限名へ変換する値。
    """

    api_key: str
    model: str
    options: AssistantGenerationConfig
    max_tokens: int | None


class OpenAIClientAdapter:
    """OpenAI SDK clientをアプリ内Protocolへ適合させる。"""

    def __init__(self, client: AsyncOpenAI) -> None:
        """Adapterを作成する。

        Args:
            client: OpenAI SDKのAsyncOpenAI client。

        Returns:
            None。
        """
        self.client = client

    async def create_responses_stream(
        self,
        *,
        model: str,
        input: list[LlmMessage],
        extra_body: AssistantGenerationConfig,
        max_output_tokens: int | None,
    ) -> AsyncGenerator[object]:
        """Responses API streamを作成し、eventをobject境界で返す。"""
        responses = getattr(self.client, "responses")
        create = getattr(responses, "create")
        result = create(
            model=model,
            input=input,
            stream=True,
            store=False,
            extra_body=extra_body,
            max_output_tokens=max_output_tokens,
        )
        stream_resource = await result if isawaitable(result) else result
        stream = _ensure_async_iterable(stream_resource)
        try:
            async for event in stream:
                yield event
        finally:
            await _close_provider_resource(stream_resource)

    async def create_chat_completions_stream(
        self,
        *,
        model: str,
        messages: list[LlmMessage],
        extra_body: AssistantGenerationConfig,
        max_tokens: int | None,
    ) -> AsyncGenerator[object]:
        """Chat Completions API streamを作成し、eventをobject境界で返す。"""
        chat = getattr(self.client, "chat")
        completions = getattr(chat, "completions")
        create = getattr(completions, "create")
        result = create(
            model=model,
            messages=messages,
            stream=True,
            extra_body=extra_body,
            max_tokens=max_tokens,
        )
        stream_resource = await result if isawaitable(result) else result
        stream = _ensure_async_iterable(stream_resource)
        try:
            async for event in stream:
                yield event
        finally:
            await _close_provider_resource(stream_resource)


async def _ensure_async_iterable(value: object) -> AsyncGenerator[object]:
    """SDKの戻り値がasync iterableであることを確認してobjectとしてyieldする。

    Args:
        value: SDKまたは互換fakeから返されたstream resource。

    Yields:
        SDK streamから得たevent object。

    Raises:
        TypeError: streamとして読めない値の場合。
    """
    if _is_object_async_iterable(value):
        async for event in value:
            yield event
        return
    raise TypeError("OpenAI stream resource must be async iterable")


def _is_object_async_iterable(value: object) -> TypeGuard[AsyncIterable[object]]:
    """値がobject eventを返すasync iterableかを型ガードする。"""
    return isinstance(value, AsyncIterable)


def _read_first_text(value: object, names: tuple[str, ...]) -> str:
    """候補属性から最初の非空文字列を取り出す。"""
    for name in names:
        item = getattr(value, name, None)
        if isinstance(item, str) and item:
            return item
    return ""


def _runtime_request_config(assistant: ResolvedAssistant) -> RuntimeRequestConfig:
    """ResolvedAssistant.configからLLM request用設定を取り出す。

    Args:
        assistant: APIキー、モデル名、APIモード、追加設定を持つAssistant。

    Returns:
        API key、model、外部APIへ送る生成オプション、token上限。

    Raises:
        ValueError: APIキーまたはモデル名が設定されていない場合。
    """
    config = dict(assistant.config)
    api_key = str(config.pop("api_key", "") or "")
    if not api_key:
        raise ValueError("API key is required in data/connection_providers.json")
    model = str(config.pop("model", "") or "")
    if not model:
        raise ValueError("model is required in assistant settings")
    max_tokens = _read_max_tokens(
        config.pop("max_output_tokens", config.pop("max_tokens", None))
    )
    for key in INTERNAL_RUNTIME_CONFIG_KEYS:
        config.pop(key, None)
    return RuntimeRequestConfig(
        api_key=api_key,
        model=model,
        options=config,
        max_tokens=max_tokens,
    )


def _read_max_tokens(value: object) -> int | None:
    """設定値からtoken上限として扱える整数を取り出す。

    Args:
        value: Assistant設定から読んだmax token値。

    Returns:
        正の整数ならその値、それ以外はNone。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


async def _close_provider_resource(resource: object) -> None:
    """`aclose()` または `close()` を持つSDK resourceを閉じる。"""
    close = getattr(resource, "aclose", None) or getattr(resource, "close", None)
    if not callable(close):
        return
    result = close()
    if isawaitable(result):
        await result


class OpenAIResponder:
    """OpenAI互換APIからチャット応答をストリーム取得する。

    `responses` と `chat_completions` の違いはこのクラス内で吸収し、
    呼び出し側は `StreamEvent("delta")` の列だけを扱えばよい形にする。
    """

    def __init__(
        self,
        clients: Mapping[str, OpenAIStreamClient] | None = None,
    ) -> None:
        """API mode別clientを受け取ってResponderを作成する。

        Args:
            clients: api_modeをkeyにしたOpenAIStreamClient。未指定なら標準2種。

        Returns:
            None。
        """
        self.clients = clients or {
            "responses": ResponsesApiClient(),
            "chat_completions": ChatCompletionsApiClient(),
        }

    async def stream(
        self,
        *,
        messages: list[LlmMessage],
        assistant: ResolvedAssistant,
    ) -> AsyncGenerator[StreamEvent]:
        """LLM応答をアプリ内部のStreamEventへ変換して返す。

        Args:
            messages: LLMへ渡す role/content の履歴。
            assistant: APIキー、モデル名、APIモード、追加設定を持つAssistant。

        Yields:
            表示可能な本文差分だけを含む `StreamEvent("delta")`。

        Raises:
            ValueError: APIキーまたはモデル名が設定されていない場合。

        OpenAI SDK の戻り値はAPIごとに形が異なるため、外側の応答service層へ
        直接渡さず、ここでアプリ標準イベントへ変換する。
        """
        runtime_config = _runtime_request_config(assistant)
        api_client = self.clients[assistant.api_mode]
        request = api_client.build_request(
            model=runtime_config.model,
            messages=messages,
            config=runtime_config.options,
            max_tokens=runtime_config.max_tokens,
        )
        sdk_client = AsyncOpenAI(
            api_key=runtime_config.api_key,
            base_url=assistant.base_url,
        )
        client = OpenAIClientAdapter(sdk_client)
        logger.info(
            "llm.start assistant_id=%s api_mode=%s base_url=%s model=%s message_count=%s config_keys=%s",
            assistant.id,
            assistant.api_mode,
            assistant.base_url,
            runtime_config.model,
            len(messages),
            sorted(runtime_config.options.keys()),
        )
        try:
            async for event in api_client.stream_events(
                client=client,
                request=request,
            ):
                yield event
        finally:
            await _close_provider_resource(sdk_client)


class ResponsesApiClient:
    """Responses APIのrequest構築とstream event変換を担当する。"""

    api_mode = "responses"

    def build_request(
        self,
        *,
        model: str,
        messages: list[LlmMessage],
        config: AssistantGenerationConfig,
        max_tokens: int | float | str | bool | None,
    ) -> LlmRequest:
        """Responses APIへ渡すrequest辞書を構築する。

        Args:
            model: 実行モデル名。
            messages: LLMへ渡す履歴。
            config: extra_bodyへ渡す生成オプション。
            max_tokens: Responses APIではmax_output_tokensへ入れる値。

        Returns:
            `responses.create` に渡せるrequest辞書。
        """
        request: LlmRequest = {
            "model": model,
            "input": messages,
            "stream": True,
            "store": False,
            "extra_body": config,
        }
        if max_tokens is not None:
            request["max_output_tokens"] = max_tokens
        return request

    async def stream_events(
        self,
        *,
        client: OpenAISdkClient,
        request: LlmRequest,
    ) -> AsyncGenerator[StreamEvent]:
        """Responses APIのstreamを読み、内部StreamEventへ変換する。"""
        stream = client.create_responses_stream(
            model=str(request["model"]),
            input=_request_messages(request, "input"),
            extra_body=_request_config(request),
            max_output_tokens=_request_optional_int(request, "max_output_tokens"),
        )
        async for event in stream:
            event_type = str(getattr(event, "type", "") or "")
            logger.debug("llm.raw_event api_mode=responses type=%s", event_type)
            if event_type.startswith("response.reasoning") and event_type.endswith(
                ".delta"
            ):
                reasoning_delta = _read_first_text(
                    event,
                    ("delta", "reasoning", "text", "content", "summary_text"),
                )
                if reasoning_delta:
                    yield StreamEvent(
                        "reasoning_delta",
                        reasoning_delta=reasoning_delta,
                    )
            if event_type == "response.output_text.delta":
                delta = str(getattr(event, "delta", "") or "")
                if delta:
                    yield StreamEvent("delta", delta=delta)


class ChatCompletionsApiClient:
    """Chat Completions APIのrequest構築とstream event変換を担当する。"""

    api_mode = "chat_completions"

    def build_request(
        self,
        *,
        model: str,
        messages: list[LlmMessage],
        config: AssistantGenerationConfig,
        max_tokens: int | float | str | bool | None,
    ) -> LlmRequest:
        """Chat Completions APIへ渡すrequest辞書を構築する。

        Args:
            model: 実行モデル名。
            messages: LLMへ渡す履歴。
            config: extra_bodyへ渡す生成オプション。
            max_tokens: Chat Completions APIではmax_tokensへ入れる値。

        Returns:
            `chat.completions.create` に渡せるrequest辞書。
        """
        request: LlmRequest = {
            "model": model,
            "messages": messages,
            "stream": True,
            "extra_body": config,
        }
        if max_tokens is not None:
            request["max_tokens"] = max_tokens
        return request

    async def stream_events(
        self,
        *,
        client: OpenAISdkClient,
        request: LlmRequest,
    ) -> AsyncGenerator[StreamEvent]:
        """Chat Completions APIのstreamを読み、内部StreamEventへ変換する。"""
        stream = client.create_chat_completions_stream(
            model=str(request["model"]),
            messages=_request_messages(request, "messages"),
            extra_body=_request_config(request),
            max_tokens=_request_optional_int(request, "max_tokens"),
        )
        async for event in stream:
            event_type = str(getattr(event, "type", "") or "")
            logger.debug(
                "llm.raw_event api_mode=chat_completions type=%s", event_type
            )
            choice = _first_choice(getattr(event, "choices", None))
            choice_delta = getattr(choice, "delta", None)
            reasoning_delta = _read_first_text(
                choice_delta,
                ("reasoning_content", "reasoning", "thinking_content", "thinking"),
            )
            if reasoning_delta:
                yield StreamEvent("reasoning_delta", reasoning_delta=reasoning_delta)
            content_delta = getattr(choice_delta, "content", None)
            if content_delta:
                text = str(content_delta)
                yield StreamEvent("delta", delta=text)


def _request_messages(request: LlmRequest, key: str) -> list[LlmMessage]:
    """request辞書からmessage配列を型付きで取り出す。

    Args:
        request: API別clientが構築したrequest辞書。
        key: `input` または `messages`。

    Returns:
        LLMへ送るmessage配列。
    """
    value = request[key]
    if isinstance(value, list):
        return value
    raise TypeError(f"{key} must be messages")


def _request_config(request: LlmRequest) -> AssistantGenerationConfig:
    """request辞書からextra_body設定を型付きで取り出す。"""
    value = request["extra_body"]
    if isinstance(value, dict):
        return value
    raise TypeError("extra_body must be config")


def _request_optional_int(request: LlmRequest, key: str) -> int | None:
    """request辞書から任意の整数値を取り出す。"""
    value = request.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _first_choice(choices: object) -> object | None:
    """Chat Completion eventのchoices先頭要素をobject境界で取り出す。"""
    if _is_object_list(choices) and choices:
        return choices[0]
    return None


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    """値がobjectのlistであることを型ガードする。"""
    return isinstance(value, list)
