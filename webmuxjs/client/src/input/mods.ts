/**
 * 修饰键位 —— `Alt=1 Ctrl=2 Meta=4 Shift=8`(`protocol/frames.md` §3)。
 *
 * 单独一个文件是因为它**纯**:给一组布尔,出一个数。
 * 服务端那边有同一张表,所以它值得被对拍。
 */

import { MOD } from "../protocol/messages.ts";

export interface ModKeys {
  altKey?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
}

export function mods(e: ModKeys): number {
  return (e.altKey ? MOD.alt : 0) | (e.ctrlKey ? MOD.ctrl : 0) |
         (e.metaKey ? MOD.meta : 0) | (e.shiftKey ? MOD.shift : 0);
}

/**
 * CSS 坐标 → **画面坐标**。
 *
 * 元素被缩放过(`width: 100%` 之类),而服务端要的是画面里的位置 ——
 * 拿 CSS 坐标直接发,点击会整体偏。
 */
export function toFrame(
  client: { x: number; y: number },
  rect: { left: number; top: number; width: number; height: number },
  cast: { w: number; h: number },
): { x: number; y: number } {
  return {
    x: (client.x - rect.left) * (cast.w / rect.width),
    y: (client.y - rect.top) * (cast.h / rect.height),
  };
}
