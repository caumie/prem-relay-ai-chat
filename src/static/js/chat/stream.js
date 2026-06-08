import { applyMessagePatch } from "./message-view.js";
import { parseStreamEvent, toMessagePatch } from "./message-payload.js";
import { isChatNearBottom, scrollChatToBottom } from "./scroll.js";

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
    closeStream(messageId, source);
  };
}

function findMessage(messageId) {
  return document.querySelector(`[data-chat-message-id="${CSS.escape(messageId)}"]`);
}

function closeStream(messageId, source) {
  source.close();
  if (activeStreams.get(messageId) === source) {
    activeStreams.delete(messageId);
    document.dispatchEvent(
      new CustomEvent("chat:stream-end", { detail: { messageId } }),
    );
  }
}
