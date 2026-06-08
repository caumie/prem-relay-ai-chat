/*
 * ストリーム payload の正規化を扱うファイル。
 *
 * SSE は外部境界であるため、UI が理解する最小形へ検証付きで正規化し、
 * message-view.js が扱う現在の MessagePatch へ変換する。
 */

/**
 * @typedef {import("./message-view.js").MessagePatch} MessagePatch
 */

/**
 * @typedef {object} ParsedStreamEvent
 * @property {string} type - サーバーが送るイベント種別。
 * @property {string=} messageId - 正規化後の対象 message id。
 * @property {string=} status - 任意の stream または message の状態値。
 * @property {string=} content - 本文の全量テキスト。
 * @property {string=} delta - 本文増分。
 * @property {string=} reasoning - reasoning の全量テキスト。
 * @property {string=} reasoningDelta - reasoning の増分テキスト。
 * @property {string=} error - 利用者へ見せるエラー文言。
 */

export function parseStreamEvent(raw) {
  try {
    const value = JSON.parse(raw);
    if (!value || typeof value !== "object" || typeof value.type !== "string") {
      return null;
    }

    return {
      type: value.type,
      messageId: readString(value.message_id) || readString(value.messageId),
      status: readString(value.status),
      content: readString(value.content),
      delta: readString(value.delta),
      reasoning: readString(value.reasoning),
      reasoningDelta:
        readString(value.reasoning_delta) || readString(value.reasoningDelta),
      error: readString(value.error),
    };
  } catch (_error) {
    return null;
  }
}

export function toMessagePatch(event) {
  if (event.type === "status") {
    return { status: event.status || "" };
  }
  if (event.type === "full") {
    return { content: event.content || "", contentMode: "replace" };
  }
  if (event.type === "delta") {
    return { content: event.delta || "", contentMode: "append" };
  }
  if (event.type === "reasoning") {
    return { reasoning: event.reasoning || "", reasoningMode: "replace" };
  }
  if (event.type === "reasoning_delta") {
    return { reasoning: event.reasoningDelta || "", reasoningMode: "append" };
  }
  if (event.type === "error") {
    return { status: "failed", error: event.error || "failed" };
  }
  if (event.type === "done") {
    return { status: "completed", done: true };
  }
  return null;
}

function readString(value) {
  return typeof value === "string" ? value : undefined;
}
