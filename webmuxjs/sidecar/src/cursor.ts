/**
 * 光标形状 —— [b §5](../../../docs/v2/works/b-input.md)。
 *
 * 远端页面里光标是什么形状,观看端就跟着变。没有这个,画面上一切都是箭头,
 * **人会分不清哪里能点**。
 *
 * **CDP 里没有「光标变了」这种事件**,screencast 的帧里也不含光标 ——
 * 光标是纯渲染层的东西。所以只能在页面里自己算。
 */

import type { Send } from "./wire.ts";

/**
 * `cursor: auto` 的语义是"文字上 I 型,别处箭头",光读计算样式区分不出来 ——
 * 两种情况读出来都是 `auto`。所以要做命中测试。
 */
function overText(x: number, y: number): boolean {
  const doc = document as Document & {
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
  };
  if (!doc.caretRangeFromPoint) return false;
  let r: Range | null;
  try {
    r = doc.caretRangeFromPoint(x, y);
  } catch {
    return false;
  }
  if (!r || !r.startContainer || r.startContainer.nodeType !== 3) return false;
  // `caretRangeFromPoint` 会"吸附"到最近的文字,
  // **不校验就会让空白处也报 I 型**
  const range = document.createRange();
  range.selectNodeContents(r.startContainer);
  for (const rect of Array.from(range.getClientRects())) {
    if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom)
      return true;
  }
  return false;
}

/**
 * **能输入的东西,`auto` 就是 I 型** —— 哪怕里面一个字都没有。
 *
 * 光靠 `overText` 判不出来:空的搜索框没有文字节点,`caretRangeFromPoint`
 * 落不到东西上,于是报箭头。而"一个空的搜索框看上去不能输入"
 * 正是这个功能要防的事。
 */
const NON_TEXT = /^(button|submit|reset|checkbox|radio|range|color|file|image)$/i;

function editable(el: Element): boolean {
  const t = el.tagName;
  if (t === "TEXTAREA") return true;
  if (t === "INPUT") return !NON_TEXT.test((el as HTMLInputElement).type || "text");
  return (el as HTMLElement).isContentEditable === true;
}

export function install(send: Send): void {
  let last = "";
  let pending = false;
  let lx = 0;
  let ly = 0;

  const read = (): void => {
    pending = false;
    let el: Element | null;
    try {
      el = document.elementFromPoint(lx, ly);
    } catch {
      return;
    }
    if (!el) return;
    let c = "default";
    try {
      c = getComputedStyle(el).cursor || "auto";
    } catch {
      /* 跨源、或者元素刚被摘掉 */
    }
    if (c === "auto") c = editable(el) || overText(lx, ly) ? "text" : "default";
    if (c === last) return; // **值变了才上报**,基本不占带宽
    last = c;
    send("cursor", { cursor: c });
  };

  const tick = (e: PointerEvent | null): void => {
    if (e) {
      lx = e.clientX;
      ly = e.clientY;
    }
    if (pending) return;
    pending = true;
    requestAnimationFrame(read); // rAF 节流
  };

  addEventListener("pointermove", (e) => tick(e as PointerEvent), true);
  addEventListener("pointerdown", (e) => tick(e as PointerEvent), true);
  addEventListener("scroll", () => tick(null), true);
}
