/**
 * `/channel/cdp` —— **JPG 帧下来,所有输入上去。**
 *
 * 这一层是**唯一碰 WebSocket 的地方**;拆头、判丢帧、攒批、回执
 * 全在 `protocol/` 和 `flow/` 里,那两层能在 node 里单独测。
 * 这儿只剩三件事:连、分流、断了重连。
 */

import { Acker } from "../flow/ack.ts";
import { Batcher } from "../flow/batch.ts";
import { HEADER_SIZE, parseHeader, shouldDrop } from "../protocol/frame.ts";
import { allowed, type Downstream, type Upstream } from "../protocol/messages.ts";

export interface CdpHandlers {
  /** 一帧图片的裸字节 + 帧号。 */
  frame(bytes: Uint8Array, frameId: number): void;
  message(m: Downstream): void;
  open(): void;
  close(): void;
}

export class CdpChannel {
  private ws: WebSocket | null = null;
  private castId = 0;
  private wantTarget = "";
  readonly acker: Acker;
  readonly batcher: Batcher;

  constructor(private url: string, private on: CdpHandlers) {
    this.acker = new Acker((m) => this.send(m));
    this.batcher = new Batcher((m) => this.send(m));
  }

  connect(): this {
    const ws = new WebSocket(this.url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => this.on.open();
    ws.onmessage = (e) => {
      if (typeof e.data !== "string") return this.onFrame(e.data as ArrayBuffer);
      this.on.message(JSON.parse(e.data) as Downstream);
    };
    ws.onclose = () => {
      this.acker.stop();
      this.on.close();
      setTimeout(() => this.connect(), 1000);
    };
    return this;
  }

  /** 切 tab / 重开一轮之后调 —— 让下一帧重新定基准。 */
  resetTarget(): void {
    this.wantTarget = "";
  }

  private onFrame(buf: ArrayBuffer): void {
    const h = parseHeader(buf);
    if (shouldDrop(h, this.castId, this.wantTarget)) return;
    this.castId = h.castSessionId;
    this.on.frame(new Uint8Array(buf, HEADER_SIZE), h.frameId);
    this.acker.got(h.frameId); // 环 B —— 背压就靠它
  }

  /**
   * **最后一道白名单。** 服务端也有同一张表;两边都守,
   * 是因为这张表就是安全模型本身。
   */
  send(m: Upstream): void {
    if (!allowed(m)) throw new Error(`不在上行白名单里:${(m as { type: string }).type}`);
    if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(m));
  }

  /** 进批的(move / wheel)。 */
  queue(m: Upstream): void { this.batcher.queue(m); }

  /** 不进批的(down / up / key / text / resize / tab / mode)。 */
  now(m: Upstream): void { this.batcher.now(m); }
}
