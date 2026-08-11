/*
 * チャット画面のスクロール補助を扱うファイル。
 *
 * メッセージ一覧のスクロール領域は画面内で一箇所なので、
 * 参照をここへ集約して form や stream 側へレイアウト依存を広げないようにする。
 */

const bottomThresholdPx = 48;
const scrollStates = new WeakMap();

/**
 * チャットのメッセージ一覧を表示するスクロール領域を返す。
 *
 * @returns {Element|null} 対象のスクロール領域。存在しなければnull。
 */
function findChatScrollRegion() {
  return document.querySelector("[data-chat-scroll-region]");
}

/**
 * 指定したスクロール領域が下端付近にあるか判定する。
 *
 * @param {Element} region - 判定対象のスクロール領域。
 * @returns {boolean} 下端から閾値以内ならtrue。
 */
function isNearBottom(region) {
  return region.scrollHeight - region.scrollTop - region.clientHeight <=
    bottomThresholdPx;
}

/**
 * スクロール位置の変化を追従状態へ反映する。
 *
 * @param {Element} region - 監視対象のスクロール領域。
 * @param {{lastScrollTop: number, shouldFollow: boolean}} state - スクロール状態。
 * @returns {void} 戻り値は持たない。
 */
function updateScrollState(region, state) {
  const currentScrollTop = region.scrollTop;
  if (currentScrollTop !== state.lastScrollTop) {
    state.shouldFollow = currentScrollTop > state.lastScrollTop;
  }
  state.lastScrollTop = currentScrollTop;
}

/**
 * 指定したスクロール領域の利用者操作を監視し、追従状態を返す。
 *
 * @param {Element} region - 監視対象のスクロール領域。
 * @returns {{lastScrollTop: number, shouldFollow: boolean}} スクロール状態。
 */
function trackScrollRegion(region) {
  const existingState = scrollStates.get(region);
  if (existingState) {
    return existingState;
  }

  const state = {
    lastScrollTop: region.scrollTop,
    shouldFollow: true,
  };
  scrollStates.set(region, state);
  region.addEventListener("scroll", () => updateScrollState(region, state));
  return state;
}

/**
 * ストリーム更新後も自動追従してよい状態か判定する。
 *
 * 上方向へのスクロールで追従を解除し、利用者が下端へ戻ったら再開する。
 *
 * @returns {boolean} ストリームの更新に追従するならtrue。
 */
export function shouldFollowChatStream() {
  const region = findChatScrollRegion();
  if (!region) {
    return false;
  }
  const state = trackScrollRegion(region);
  updateScrollState(region, state);
  return state.shouldFollow && isNearBottom(region);
}

/**
 * メッセージ領域が存在する場合に最下部までスクロールする。
 *
 * @returns {void} 戻り値は持たない。
 */
export function scrollChatToBottom() {
  const region = findChatScrollRegion();
  if (!region) {
    return;
  }

  const state = trackScrollRegion(region);
  region.scrollTop = region.scrollHeight;
  state.lastScrollTop = region.scrollTop;
  state.shouldFollow = true;
}
