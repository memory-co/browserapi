/**
 * **有人在动这一页** —— 以及动的是哪个东西。
 *
 * 两件事靠它:
 *
 * 1. `busy_human` —— 人正在操作的时候,API 那边的**写**要让路
 *    ([works/06 §3.2](../../../docs/v1/works/06-tab-sync.md))
 * 2. 流水 —— 人干的事也要进 `webmuxd log`,不然那条流水里只有 API 干过的事,
 *    排查的时候等于少了一半
 *
 * **CDP 派发的输入在页面里 `isTrusted === true`**,和真人点的一模一样,
 * 页面脚本分不出来。所以这儿只负责"有输入",谁干的由服务端拿
 * "我刚派发了什么"做相关性 —— 那是 `sessions.py` 的事,不是这儿的。
 */

import { label } from "./label.ts";
import type { Send } from "./wire.ts";

export function install(send: Send): void {
  const report = (kind: "pointerdown" | "keydown", e: Event): void => {
    const t = e.target as Element | null;
    const m = e as MouseEvent;
    send(kind, {
      x: m.clientX | 0,
      y: m.clientY | 0,
      role: ((t && (t.getAttribute("role") || t.tagName)) || "").toLowerCase(),
      name: label(t).toString().trim().slice(0, 40),
      at: Date.now(),
    });
  };

  // **捕获阶段** —— 页面 `stopPropagation` 也拦不住我们
  addEventListener("pointerdown", (e) => report("pointerdown", e), true);
  addEventListener("keydown", (e) => report("keydown", e), true);
}
