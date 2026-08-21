/**
 * 环 B:**收到一帧就回执**,以及那条自愈的心跳。
 *
 * 三条(`server/protocol/channels.md`):
 *
 * - **立即发** —— 它同时是 RTT 探针,一排队就测不准
 * - **带帧号** —— 服务端靠它算 RTT,不是靠"收到了几个"
 * - **不搭车** —— 不跟输入合并发,理由同上
 *
 * 外加一条 **3 秒心跳**:某一帧要是丢在路上,客户端永远等不到、
 * 也就永远不 ack,服务端额度耗尽就是**永久卡死**。补一发就自愈了。
 *
 * 纯逻辑:定时器和"往哪发"都从外面给,所以能在 node 里测。
 */

import { ack, type Ack } from "../protocol/messages.ts";

export const HEARTBEAT_MS = 3000;

type Send = (m: Ack) => void;
type SetTimer = (fn: () => void, ms: number) => unknown;
type ClearTimer = (h: unknown) => void;

export class Acker {
  private lastFrameId = 0;
  private timer: unknown = null;

  constructor(
    private send: Send,
    // **必须包一层,不能直接把 `setTimeout` 传进来。**
    // 它会变成这个对象的方法被调用,而浏览器要求 `setTimeout` 的接收者是
    // `window` —— 直接传的话真浏览器里抛 `Illegal invocation`,
    // 而单测因为总是喂假定时器,**永远走不到这条默认路径**。
    private setTimer: SetTimer = (fn, ms) => setTimeout(fn, ms),
    private clearTimer: ClearTimer = (h) => clearTimeout(h as number),
    private heartbeatMs = HEARTBEAT_MS,
  ) {}

  /** 收到一帧。**立刻回,然后把心跳往后推。** */
  got(frameId: number): void {
    this.lastFrameId = frameId;
    this.fire(frameId);
  }

  private fire(frameId: number): void {
    this.send(ack(frameId));
    this.clearTimer(this.timer);
    this.timer = this.setTimer(() => this.fire(this.lastFrameId), this.heartbeatMs);
  }

  /** 连接断了 —— 心跳要停,否则重连之后会打在旧连接上。 */
  stop(): void {
    this.clearTimer(this.timer);
    this.timer = null;
  }
}
