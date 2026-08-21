/**
 * 键盘和 IME —— **组字全在本地,`compositionend` 才发最终文本**。
 *
 * 这是 v2 相对 VNC 的**净胜,不是打平**:VNC 那条路上每一次候选框变化
 * 都要走一个来回,弱网下中文基本没法打;这儿组字完全是本地的,
 * 一次输入只上行一条 `text`([b §3](../../../../docs/v2/works/b-input.md))。
 *
 * 落点是一个隐藏 `<textarea>`:浏览器只对可编辑元素开 IME,
 * 所以必须有这么一个东西接住焦点。
 */

import type { Key, Text } from "../protocol/messages.ts";
import { mods } from "./mods.ts";

export interface KeyTarget {
  now(m: Key | Text): void;
}

export function bindKeyboard(ime: HTMLTextAreaElement, t: KeyTarget): void {
  let composing = false;

  ime.addEventListener("compositionstart", () => { composing = true; });
  ime.addEventListener("compositionend", (e) => {
    composing = false;
    if (e.data) t.now({ type: "text", text: e.data });
    ime.value = "";
  });

  ime.addEventListener("keydown", (e) => {
    if (composing) return;              // **组字期间一个按键都不发**
    // Tab 会把焦点弹走,Ctrl+W / Ctrl+T 会动观看者自己的浏览器
    if (e.key === "Tab" || (e.ctrlKey && "wt".includes(e.key))) e.preventDefault();
    t.now({ type: "key", event: "down", key: e.key, code: e.code, modifiers: mods(e) });
  });
  ime.addEventListener("keyup", (e) => {
    if (composing) return;
    t.now({ type: "key", event: "up", key: e.key, code: e.code, modifiers: mods(e) });
  });

  ime.addEventListener("paste", (e) => {
    e.preventDefault();
    const text = e.clipboardData?.getData("text");
    if (text) t.now({ type: "text", text });
  });

  // textarea 只是个接焦点的壳,**不留内容** —— 留着的话下一次粘贴会连旧的一起发
  ime.addEventListener("input", () => { if (!composing) ime.value = ""; });
}
