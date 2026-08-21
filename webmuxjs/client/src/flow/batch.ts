/**
 * 输入聚批 —— **移动和滚轮攒 25ms 一批**。
 *
 * 一秒几十个 mousemove,逐个发是在给自己制造排队 ——
 * 而中间那些位置**没有任何人关心**,只有最后那个是"鼠标现在在哪"。
 *
 * 三条规则,每条都有代价在后面顶着:
 *
 * - **同一批里只留最后一个 move** —— 中间的位置没人关心
 * - **滚轮要累加,不能只留最后一个** —— 丢掉的每一格都是真滚过的距离
 * - **按下、抬起、按键不进批** —— 25ms 在点击上能感觉出来,而且
 *   down 和 up 之间插 25ms,有的页面会判成长按
 *
 * 回执永远不进批(见 `ack.ts`)。
 *
 * 纯逻辑,定时器从外面给。
 */

import type { Mouse, Upstream, Wheel } from "../protocol/messages.ts";

export const BATCH_MS = 25;

type Send = (m: Upstream) => void;
type SetTimer = (fn: () => void, ms: number) => unknown;

export class Batcher {
  private move: Mouse | null = null;
  private wheel: Wheel | null = null;
  private timer: unknown = null;

  constructor(
    private send: Send,
    // 包一层,理由见 `ack.ts` —— 直接传 `setTimeout` 在真浏览器里是
    // `Illegal invocation`。
    private setTimer: SetTimer = (fn, ms) => setTimeout(fn, ms),
    private ms = BATCH_MS,
  ) {}

  /** 进批的走这条。 */
  queue(m: Upstream): void {
    if (m.type === "mouse" && m.event === "move") {
      this.move = m; // 只留最后一个
    } else if (m.type === "wheel") {
      this.wheel = this.wheel
        ? { ...m, dx: this.wheel.dx + m.dx, dy: this.wheel.dy + m.dy }
        : m;
    } else {
      this.send(m);
      return;
    }
    if (!this.timer) this.timer = this.setTimer(() => this.flush(), this.ms);
  }

  /**
   * 不进批的走这条。**先把攒着的位置发掉** ——
   * 否则远端收到的"点击位置"是上一个采样点。
   */
  now(m: Upstream): void {
    this.flush();
    this.send(m);
  }

  flush(): void {
    this.timer = null;
    if (this.move) { this.send(this.move); this.move = null; }
    if (this.wheel) { this.send(this.wheel); this.wheel = null; }
  }
}
