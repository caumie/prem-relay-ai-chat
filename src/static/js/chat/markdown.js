/*
 * Markdown 描画の境界を扱うファイル。
 *
 * メッセージ本文は初期HTMLにも SSE の増分にも現れるため、
 * markdown-it の有無をここで吸収し、描画側は一つの関数だけを呼べばよい形にする。
 */

const markdown = typeof window.markdownit === "function"
  ? window.markdownit({ html: false, linkify: true, breaks: true })
  : null;

/**
 * Markdown 文字列を描画し、ライブラリが無い場合は plain text として表示する。
 *
 * @param {Element} target - 描画先の要素。
 * @param {string} text - 描画対象の生テキスト。
 * @returns {void} 戻り値は持たない。
 */
export function renderMarkdown(target, text) {
  if (markdown) {
    target.innerHTML = markdown.render(text);
    return;
  }

  target.textContent = text;
}
