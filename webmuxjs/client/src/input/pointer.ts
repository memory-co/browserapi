/**
 * 鼠标和滚轮 —— DOM 事件 → 上行消息。
 *
 * **客户端只做归一化**,翻译成 CDP `Input.*` 在服务端
 * ([b §1](../../../../docs/v2/works/b-input.md#1-收口在哪))。
 *
 * 三个元素都绑(`<img>` / `<canvas>` / DOM 容器):只有一个是可见的,
 * 事件只会从那个上来 —— **比"切换时重新绑"少一个会忘的状态**。
 */

import type { Mouse, Wheel } from "../protocol/messages.ts";
import { mods, toFrame } from "./mods.ts";

export interface PointerTarget {
  /** 当前画面元素 —— 切换画面时会变,所以是个函数不是个值。 */
  el(): HTMLElement;
  cast(): { w: number; h: number };
  /** 进批的(move / wheel)。 */
  queue(m: Mouse | Wheel): void;
  /** 不进批的(down / up)。 */
  now(m: Mouse): void;
  /** 按下时把焦点还给那个隐藏 textarea,否则 IME 收不到。 */
  focus(): void;
}

function at(t: PointerTarget, e: MouseEvent | WheelEvent) {
  const el = t.el();
  return toFrame({ x: e.clientX, y: e.clientY },
                 el.getBoundingClientRect(), t.cast());
}

export function bindPointer(els: HTMLElement[], t: PointerTarget): void {
  for (const el of els) {
    el.addEventListener("mousemove", (e) => {
      t.queue({ type: "mouse", event: "move", ...at(t, e),
                buttons: e.buttons, modifiers: mods(e) });
    });
    el.addEventListener("mousedown", (e) => {
      e.preventDefault();
      t.focus();
      t.now({ type: "mouse", event: "down", ...at(t, e), button: e.button,
              buttons: e.buttons, clicks: e.detail || 1, modifiers: mods(e) });
    });
    el.addEventListener("contextmenu", (e) => e.preventDefault());
    el.addEventListener("wheel", (e) => {
      e.preventDefault();
      t.queue({ type: "wheel", ...at(t, e), dx: e.deltaX, dy: e.deltaY,
                modifiers: mods(e) });
    }, { passive: false });
  }
  // **抬起绑在 window 上**:按下之后拖出画面再松手,元素上收不到 mouseup,
  // 远端就会一直以为按钮还按着。
  addEventListener("mouseup", (e) => {
    t.now({ type: "mouse", event: "up", ...at(t, e), button: e.button,
            buttons: e.buttons, clicks: e.detail || 1, modifiers: mods(e) });
  });
}
