/**
 * xpra 的 8 字节头 —— **纯粹的拆包**,不碰 WebSocket、不碰 canvas。
 *
 *     0    'P' (0x50)
 *     1    协议标志(rencodeplus = 0x10)
 *     2    压缩 level —— **我们报了不支持,所以这里只接受 0**
 *     3    chunk 下标 —— 0 是包本体,>0 是裸字节(像素)
 *     4-7  body 长度,uint32 **大端**
 *
 * 一个逻辑包可能由若干条 WS 消息拼出来,而且像素那块是单独的 chunk ——
 * 所以这里是个**增量拆包器**:喂进来多少字节都行,吐出来完整的包。
 *
 * 放在 `protocol/` 而不是 `channel/`,判据只有一条:
 * **它能在 node 里测**([j §4.1](../../../../../docs/v2/works/j-layout.md#41-分层的判据是能不能在-node-里测))。
 * 而拆包正是最该被单独测的东西 —— 拆错了不报错,只表现成"画面偶尔卡住"。
 */

import { rdecode } from "./rencode.ts";

export const HEADER = 8;
export const MAGIC = 0x50; // 'P'
export const RENCODEPLUS = 0x10;

/**
 * 我们能解的编码。**报什么服务端就只发什么** ——
 * 这张表就是"客户端要背多重"的全部答案,不报视频编码就永远不会收到 h264。
 */
export const ENCODINGS = [
  "jpeg", "png", "png/P", "png/L", "webp", "rgb", "rgb24", "rgb32",
  "scroll", "void",
] as const;

/** 解出来的一个包:`p[0]` 是包名,数字下标上挂着对应的裸字节 chunk。 */
export type Packet = any[] & Record<number, any>;

export class ProtocolError extends Error {}

export class Framer {
  private buf: Uint8Array<ArrayBufferLike> = new Uint8Array(0);
  private raw: Record<number, Uint8Array> = {};

  /** 喂一段字节,吐出这一段能凑出来的所有完整包。**吐不出来就是还没齐**。 */
  feed(chunk: Uint8Array): Packet[] {
    if (this.buf.length) {
      const merged = new Uint8Array(this.buf.length + chunk.length);
      merged.set(this.buf);
      merged.set(chunk, this.buf.length);
      this.buf = merged;
    } else {
      this.buf = chunk;
    }

    const out: Packet[] = [];
    for (;;) {
      if (this.buf.length < HEADER) return out;
      if (this.buf[0] !== MAGIC) throw new ProtocolError("头一个字节不是 'P'");
      const level = this.buf[2]!;
      const index = this.buf[3]!;
      const size = new DataView(
        this.buf.buffer, this.buf.byteOffset + 4, 4,
      ).getUint32(0);
      if (this.buf.length < HEADER + size) return out;
      const body = this.buf.subarray(HEADER, HEADER + size);

      // **不静默降级。** 我们报了不支持压缩,服务端还压就是我们理解错了协议,
      // 硬报出来 —— 悄悄丢掉只会变成"画面偶尔卡住"这种查不动的毛病。
      if (level !== 0) {
        throw new ProtocolError(`下行带压缩 level=${level},但我们报的是不支持`);
      }

      if (index > 0) {
        this.raw[index] = new Uint8Array(body); // 拷一份,下面要挪 buf
      } else {
        let p: Packet;
        try {
          p = rdecode(body);
        } catch (err) {
          throw new ProtocolError(`包解不开:${(err as Error).message}`);
        }
        for (const k of Object.keys(this.raw)) p[Number(k)] = this.raw[Number(k)];
        this.raw = {};
        out.push(p);
      }
      this.buf = this.buf.subarray(HEADER + size);
    }
  }
}

/** 把一个包封成上行字节。上行只有 6 种包,全走同一条路。 */
export function frame(body: Uint8Array): Uint8Array {
  const out = new Uint8Array(HEADER + body.length);
  out[0] = MAGIC;
  out[1] = RENCODEPLUS;
  out[2] = 0; // 不压缩
  out[3] = 0; // 包本体
  new DataView(out.buffer).setUint32(4, body.length);
  out.set(body, HEADER);
  return out;
}
