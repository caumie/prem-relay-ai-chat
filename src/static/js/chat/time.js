/*
 * メッセージ時刻のローカライズを扱うファイル。
 *
 * サーバーは安定した UTC 表記を出し、ブラウザ側でだけ利用者の locale に合わせて
 * 表示を上書きする。これにより template 側へ locale 依存を持ち込まない。
 */

/**
 * 指定した root 配下の時刻表示をローカル時刻へ変換する。
 *
 * @param {Document|Element} root - 時刻表示を探索する起点要素。
 * @returns {void} 戻り値は持たない。
 */
export function mountTimestamps(root) {
  root.querySelectorAll("[data-chat-timestamp][data-chat-timestamp-utc]")
    .forEach((element) => {
      const utcIso = element.dataset.chatTimestampUtc || "";
      const formatted = formatToLocal(utcIso);
      if (formatted) {
        element.textContent = formatted;
      }
    });
}

/**
 * UTC の ISO 文字列を現在のブラウザ locale 向けの表示へ変換する。
 *
 * @param {string} utcIso - サーバーが返した ISO 形式の UTC 時刻文字列。
 * @returns {string|null} 変換結果。入力が不正なら null。
 */
function formatToLocal(utcIso) {
  const date = new Date(utcIso);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  const formatter = new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
  return formatter.format(date);
}
