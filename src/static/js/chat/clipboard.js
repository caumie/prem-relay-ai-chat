/*
 * メッセージのクリップボード操作を扱うファイル。
 *
 * copy は本文だけを対象にし、reasoning は本文とは別パートとして扱う。
 */

import { getMessageAnswerText } from "./message-view.js";

/**
 * 指定した root 配下のコピーボタンへイベントを取り付ける。
 *
 * @param {Document|Element} root - コピーボタン探索の起点要素。
 * @returns {void} 戻り値は持たない。
 */
export function mountClipboard(root) {
  root.querySelectorAll("[data-chat-copy-message]").forEach((button) => {
    if (button.dataset.chatCopyMounted === "true") {
      return;
    }
    button.dataset.chatCopyMounted = "true";
    button.addEventListener("click", () => copyMessage(button));
  });
}

/**
 * ボタンに対応するメッセージ本文をコピーし、短時間だけ完了表示へ切り替える。
 *
 * @param {Element} button - `data-chat-message` 配下にあるコピーボタン。
 * @returns {Promise<void>} コピー処理完了後に解決される Promise。
 */
async function copyMessage(button) {
  const message = button.closest("[data-chat-message]");
  const text = message ? getMessageAnswerText(message) : "";
  if (!text) {
    return;
  }

  await writeClipboard(text);
  markCopied(button);
}

/**
 * テキストをクリップボードへ書き込み、失敗時は古い API へフォールバックする。
 *
 * @param {string} text - コピー対象の plain text。
 * @returns {Promise<void>} コピー試行完了後に解決される Promise。
 */
async function writeClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (_error) {
    const temp = document.createElement("textarea");
    temp.value = text;
    temp.setAttribute("readonly", "");
    temp.style.position = "absolute";
    temp.style.left = "-9999px";
    document.body.appendChild(temp);
    temp.select();
    document.execCommand("copy");
    document.body.removeChild(temp);
  }
}

/**
 * コピーボタンへ一時的な完了表示を出す。
 *
 * @param {Element} button - icon と aria-label を切り替える対象ボタン。
 * @returns {void} 戻り値は持たない。
 */
function markCopied(button) {
  const icon = button.querySelector("i");
  const label = button.getAttribute("aria-label") || "Copy message";
  button.setAttribute("aria-label", "Copied");
  if (icon) {
    icon.classList.remove("fa-copy");
    icon.classList.add("fa-check");
  }

  window.setTimeout(() => {
    button.setAttribute("aria-label", label);
    if (icon) {
      icon.classList.remove("fa-check");
      icon.classList.add("fa-copy");
    }
  }, 1200);
}
