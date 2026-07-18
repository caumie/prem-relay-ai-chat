/*
 * assistant messageごとのEventSourceと表示更新を管理する。
 *
 * applicationのerror/doneだけを応答の終端としてフォームへ通知する。
 * 一時切断やlocal Jobを持たないserverの応答終了は終端ではないため、
 * EventSource標準の再接続に任せて最終DB状態を再確認する。
 */

import { applyMessagePatch } from "./message-view.js";
import { parseStreamEvent, toMessagePatch } from "./message-payload.js";
import { isChatNearBottom, scrollChatToBottom } from "./scroll.js";

// HTMXによる再mountでも同じmessageへ接続を重複生成しないため、IDで所有する。
const activeStreams = new Map();

export function mountStreams(root) {
  root.querySelectorAll("[data-chat-stream-url]").forEach(startStream);
}

function startStream(message) {
  const url = message.getAttribute("data-chat-stream-url");
  const messageId = message.getAttribute("data-chat-message-id");
  if (!url || !messageId || activeStreams.has(messageId)) {
    return;
  }

  const source = new EventSource(url);
  activeStreams.set(messageId, source);
  document.dispatchEvent(
    new CustomEvent("chat:stream-start", { detail: { messageId } }),
  );

  source.onmessage = (event) => {
    const streamEvent = parseStreamEvent(event.data);
    if (!streamEvent) {
      return;
    }

    const target = findMessage(streamEvent.messageId || messageId) || message;
    const patch = toMessagePatch(streamEvent);
    if (!patch) {
      return;
    }

    const shouldFollowStream = isChatNearBottom();
    applyMessagePatch(target, patch);
    // serverが確定したapplication終端だけをprocessing解除条件にする。
    if (patch.error) {
      closeStream(messageId, source);
    }
    if (patch.done) {
      closeStream(messageId, source);
    }
    if (shouldFollowStream) {
      scrollChatToBottom();
    }
  };

  source.onerror = () => {
    // 一時切断やnon-owner serverのEOFではCONNECTINGとなる。ここで閉じると
    // native再接続によるDB終端の再確認を失うため、再試行不能時だけ片付ける。
    if (source.readyState === EventSource.CLOSED) {
      closeStream(messageId, source);
    }
  };
}

function findMessage(messageId) {
  return document.querySelector(`[data-chat-message-id="${CSS.escape(messageId)}"]`);
}

function closeStream(messageId, source) {
  source.close();
  // 古いsourceや重複callbackからstream-endを出し、現行接続中のフォームを
  // 誤って解除しないよう、Mapを所有するsourceだけが終了を通知する。
  if (activeStreams.get(messageId) === source) {
    activeStreams.delete(messageId);
    document.dispatchEvent(
      new CustomEvent("chat:stream-end", { detail: { messageId } }),
    );
  }
}
