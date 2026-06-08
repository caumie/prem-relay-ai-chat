/*
 * チャット画面のスクロール補助を扱うファイル。
 *
 * メッセージ一覧のスクロール領域は画面内で一箇所なので、
 * 参照をここへ集約して form や stream 側へレイアウト依存を広げないようにする。
 */

const bottomThresholdPx = 48;

export function isChatNearBottom() {
  const region = document.querySelector("[data-chat-scroll-region]");
  return region
    ? region.scrollHeight - region.scrollTop - region.clientHeight <=
        bottomThresholdPx
    : false;
}

/**
 * メッセージ領域が存在する場合に最下部までスクロールする。
 *
 * @returns {void} 戻り値は持たない。
 */
export function scrollChatToBottom() {
  const region = document.querySelector("[data-chat-scroll-region]");
  if (region) {
    region.scrollTop = region.scrollHeight;
  }
}
