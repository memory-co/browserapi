/**
 * 28 字节定长帧头 —— 编、解,以及"这一帧还要不要"。
 *
 * 契约在 `webmuxjs/server/protocol/frames.md` §1,Python 那侧是
 * `webmuxd/frames.py`。**两边靠 `fixtures/frame-header.json` 对拍** ——
 * 字节序这种错不会报错,只会"画面对不上",类型也拦不住它。
 *
 * 这个文件**不碰 DOM、不碰 WebSocket**,所以能在 node 里直接测。
 */

export const HEADER_SIZE = 28;

export interface FrameHeader {
  castSessionId: number;
  frameId: number;
  /** 32 个小写 hex 字符 */
  targetId: string;
}

/** 32 个 hex → 4 个 uint32。短了补零、长了截断 —— **头是定长的**。 */
export function packTarget(targetId: string): [number, number, number, number] {
  const h = (targetId || "").padEnd(32, "0").slice(0, 32);
  const out: number[] = [];
  for (let i = 0; i < 4; i++) {
    const n = Number.parseInt(h.slice(i * 8, i * 8 + 8), 16);
    out.push(Number.isNaN(n) ? 0 : n >>> 0);
  }
  return out as [number, number, number, number];
}

export function buildHeader(h: FrameHeader): Uint8Array {
  const buf = new ArrayBuffer(HEADER_SIZE);
  const dv = new DataView(buf);
  dv.setUint32(0, h.castSessionId >>> 0, true);
  dv.setUint32(4, h.frameId >>> 0, true);
  const t = packTarget(h.targetId);
  for (let i = 0; i < 4; i++) dv.setUint32(8 + i * 4, t[i]!, true);
  dv.setUint32(24, 0, true);
  return new Uint8Array(buf);
}

export function parseHeader(buf: ArrayBuffer | Uint8Array): FrameHeader {
  const u8 = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  if (u8.byteLength < HEADER_SIZE) throw new Error(`帧头不足 ${HEADER_SIZE} 字节`);
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  let targetId = "";
  for (let i = 0; i < 4; i++) {
    targetId += dv.getUint32(8 + i * 4, true).toString(16).padStart(8, "0");
  }
  return {
    castSessionId: dv.getUint32(0, true),
    frameId: dv.getUint32(4, true),
    targetId,
  };
}

/** 帧的图片裸字节。 */
export function payload(buf: ArrayBuffer): Uint8Array {
  return new Uint8Array(buf, HEADER_SIZE);
}

/**
 * 这一帧还要不要。**两条规则缺一条都会看到闪烁**(frames.md §2):
 *
 * - `castSessionId` 比当前小的丢 —— 上一轮 startScreencast 的残帧
 * - `targetId` 和当前 tab 对不上的丢 —— 切 tab 的瞬间管道里还有旧的
 *
 * `seenCast === 0` / `wantTarget === ""` 表示"还不知道",一律收下。
 */
export function shouldDrop(
  h: FrameHeader, seenCast: number, wantTarget: string,
): boolean {
  if (seenCast && h.castSessionId < seenCast) return true;
  if (wantTarget && h.targetId !== wantTarget) return true;
  return false;
}
