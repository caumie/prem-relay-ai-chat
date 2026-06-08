/*
 * メッセージ表示モデルの描画を扱うファイル。
 *
 * チャットメッセージを本文、reasoning、status を持つ複合表示として扱う。
 * stream payload や初期 HTML は先に MessagePatch へ正規化し、
 * DOM 更新の責務だけをこの module に閉じ込める。
 */

import { renderMarkdown } from "./markdown.js";

/**
 * @typedef {object} MessagePatch
 * @property {string=} content - 本文の全量、または追記対象の増分テキスト。
 * @property {"replace"|"append"=} contentMode - 本文を置換するか追記するか。
 * @property {string=} reasoning - reasoning の全量、または追記対象の増分テキスト。
 * @property {"replace"|"append"=} reasoningMode - reasoning を置換するか追記するか。
 * @property {string=} status - `streaming` や `completed` などの状態値。
 * @property {string=} error - ストリーム失敗時に利用者へ見せる文言。
 * @property {boolean=} done - ストリーム完了として扱うべきかどうか。
 */

export function renderExistingMessages(root) {
  root.querySelectorAll("[data-chat-message-body]").forEach((body) => {
    const raw = body.dataset.chatRawContent || "";
    if (raw) {
      renderMessageBody(body, raw, "replace");
    }
  });
  root.querySelectorAll("[data-chat-message]").forEach((message) => {
    const reasoning = message.querySelector("[data-chat-message-reasoning-body]");
    const raw = reasoning?.dataset.chatRawReasoning || "";
    if (raw) {
      renderReasoning(message, raw, "replace");
      setReasoningOpen(message, message.dataset.chatMessageStatus === "processing");
    }
  });
}

export function applyMessagePatch(message, patch) {
  const body = message.querySelector("[data-chat-message-body]");
  if (body && patch.content !== undefined) {
    renderMessageBody(body, patch.content, patch.contentMode || "replace");
    if (patch.content) {
      setReasoningOpen(message, false);
    }
  }

  if (patch.reasoning !== undefined) {
    renderReasoning(message, patch.reasoning, patch.reasoningMode || "replace");
    setReasoningOpen(message, true);
  }

  if (patch.status) {
    message.dataset.chatMessageStatus = patch.status;
  }

  if (body && patch.error && !(body.dataset.chatRawContent || "")) {
    body.textContent = patch.error;
  }

  if (patch.error || patch.done) {
    message.classList.remove("streaming");
    message.removeAttribute("data-chat-stream-url");
    message.querySelector("[data-chat-cancel-button]")?.remove();
    setReasoningOpen(message, false);
  }
}

export function getMessageAnswerText(message) {
  const body = message.querySelector("[data-chat-message-body]");
  if (!body) {
    return "";
  }
  return body.dataset.chatRawContent || body.textContent || "";
}

function renderMessageBody(body, text, mode) {
  const nextText = mode === "append"
    ? (body.dataset.chatRawContent || "") + text
    : text;
  body.dataset.chatRawContent = nextText;
  renderMarkdown(body, nextText);
}

function renderReasoning(message, text, mode) {
  const container = message.querySelector("[data-chat-message-reasoning]");
  const body = message.querySelector("[data-chat-message-reasoning-body]");
  if (!container || !body) {
    return;
  }

  const nextText = mode === "append"
    ? (body.dataset.chatRawReasoning || "") + text
    : text;
  body.dataset.chatRawReasoning = nextText;
  renderMarkdown(body, nextText);
  container.hidden = !nextText;
}

function setReasoningOpen(message, open) {
  const container = message.querySelector("[data-chat-message-reasoning]");
  if (container instanceof HTMLDetailsElement && !container.hidden) {
    container.open = open;
  }
}
