/*
 * チャット機能全体の組み立てを扱うファイル。
 *
 * チャット画面の公開入口を一つにまとめ、機能別の mount 関数を調停する。
 * HTMX の差し替え契機を各機能へ漏らさず、各 module は繰り返し mount されても
 * 安全に動く前提で構成する。
 */

import { mountClipboard } from "./clipboard.js";
import { mountChatForm } from "./form.js";
import { renderExistingMessages } from "./message-view.js";
import { scrollChatToBottom } from "./scroll.js";
import { mountStreams } from "./stream.js";
import { mountTimestamps } from "./time.js";

/**
 * 指定した root 配下にチャット機能を取り付ける。
 *
 * @param {Document|Element|EventTarget|null} root - 初期表示の document か HTMX の差し替え対象。
 * @returns {void} 戻り値は持たない。
 */
export function mountChat(root) {
  const container = root instanceof Document || root instanceof Element
    ? root
    : document;

  mountChatForm(document);
  renderExistingMessages(container);
  mountClipboard(container);
  mountStreams(container);
  mountTimestamps(container);
  scrollChatToBottom();
}
