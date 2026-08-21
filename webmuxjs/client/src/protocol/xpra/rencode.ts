// rencodeplus —— xpra 的包编码。webmuxjs/server/protocol/channels.md。
//
// **只是一个格式,不大。** 下面这张表就是全部:
//
//     0..43     正的定长整数,值就是这个字节
//     44        float64(8 字节大端)
//     48..57    '0'..'9' —— 变长字符串的长度前缀,":" 收尾是文本,"/" 收尾是字节
//     59        变长数组,127 收尾
//     60        变长字典,127 收尾
//     61        任意长整数:十进制字符串,127 收尾
//     62/63/64/65   int8 / int16 / int32 / int64
//     66        float32
//     67/68/69  true / false / null
//     70..101   负的定长整数,-1-(b-70)
//     102..126  定长字典,长度 b-102
//     127       终止符
//     128..191  定长字符串,长度 b-128
//     192..255  定长数组,长度 b-192
//
// 我们**解全套、编一个子集** —— 上行只有 6 种包(works/12 §7),
// 全部用显式的变长形式编就够了,不需要为了省几个字节去挑最短表示。
//
// **这一层不碰 DOM、不碰 WebSocket**,所以能在 node 里直接测
// ([j §4.1](../../../../../docs/v2/works/j-layout.md#41-分层的判据是能不能在-node-里测))。
// 编解码错了不会报错,只会"画面对不上" —— 正是最该被单独测的那种代码。

const TERM = 127;
const utf8d = new TextDecoder("utf-8");
const utf8e = new TextEncoder();

class Reader {
  b: Uint8Array;
  i: number;
  constructor(u8: Uint8Array) { this.b = u8; this.i = 0; }
  byte(): number { return this.b[this.i++]!; }
  peek(): number { return this.b[this.i]!; }
  take(n: number): Uint8Array { const s = this.b.subarray(this.i, this.i + n); this.i += n; return s; }
  view(n: number): DataView { const d = new DataView(this.b.buffer, this.b.byteOffset + this.i, n); this.i += n; return d; }
}

function readItem(r: Reader): any {
  const c = r.byte();
  if (c < 44) return c;                                   // 正定长整数
  if (c === 44) return r.view(8).getFloat64(0);
  if (c >= 48 && c <= 57) { r.i--; return readString(r); }
  if (c === 59) { const a: any[] = []; while (r.peek() !== TERM) a.push(readItem(r)); r.i++; return a; }
  if (c === 60) { const o: Record<string, any> = {}; while (r.peek() !== TERM) { const k = readItem(r); o[k] = readItem(r); } r.i++; return o; }
  if (c === 61) {                                          // 十进制字符串整数
    let j = r.i; while (r.b[j] !== TERM) j++;
    const n = parseInt(utf8d.decode(r.b.subarray(r.i, j)), 10);
    r.i = j + 1; return n;
  }
  if (c === 62) return r.view(1).getInt8(0);
  if (c === 63) return r.view(2).getInt16(0);
  if (c === 64) return r.view(4).getInt32(0);
  if (c === 65) { const v = r.view(8).getBigInt64(0); return Number(v); }
  if (c === 66) return r.view(4).getFloat32(0);
  if (c === 67) return true;
  if (c === 68) return false;
  if (c === 69) return null;
  if (c >= 70 && c <= 101) return -1 - (c - 70);
  if (c >= 102 && c <= 126) {                              // 定长字典
    const o: Record<string, any> = {}, n = c - 102;
    for (let k = 0; k < n; k++) { const key = readItem(r); o[key] = readItem(r); }
    return o;
  }
  if (c >= 128 && c <= 191) return utf8d.decode(r.take(c - 128));
  if (c >= 192) { const a: any[] = [], n = c - 192; for (let k = 0; k < n; k++) a.push(readItem(r)); return a; }
  throw new Error("rencode: 不认识的类型 " + c);
}

function readString(r: Reader): string | Uint8Array {
  let j = r.i;
  while (r.b[j]! >= 0x30 && r.b[j]! <= 0x39) j++;
  const len = parseInt(utf8d.decode(r.b.subarray(r.i, j)), 10);
  const binary = r.b[j] === 0x2f;                          // '/' = 字节串
  r.i = j + 1;
  const bytes = r.take(len);
  // **字节串原样返回。** 像素那一块虽然走 chunk 不走这里,但 options 里
  // 有的字段是字节串,decode 成字符串会毁掉它。
  return binary ? new Uint8Array(bytes) : utf8d.decode(bytes);
}

export function rdecode(u8: Uint8Array): any { return readItem(new Reader(u8)); }

// ------------------------------------------------------------------ 编

function push(out: Uint8Array[], arr: Uint8Array) { out.push(arr); }

function enc(v: any, out: Uint8Array[]): void {
  if (v === null || v === undefined) { push(out, Uint8Array.of(69)); return; }
  if (typeof v === "boolean") { push(out, Uint8Array.of(v ? 67 : 68)); return; }
  if (typeof v === "number") {
    if (Number.isInteger(v)) {
      if (v >= 0 && v < 44) { push(out, Uint8Array.of(v)); return; }
      const b = new Uint8Array(9); const d = new DataView(b.buffer);
      b[0] = 65; d.setBigInt64(1, BigInt(v)); push(out, b); return;
    }
    const b = new Uint8Array(9); const d = new DataView(b.buffer);
    b[0] = 44; d.setFloat64(1, v); push(out, b); return;
  }
  if (typeof v === "string") {
    const s = utf8e.encode(v), p = utf8e.encode(String(s.length) + ":");
    const b = new Uint8Array(p.length + s.length);
    b.set(p); b.set(s, p.length); push(out, b); return;
  }
  if (v instanceof Uint8Array) {
    const p = utf8e.encode(String(v.length) + "/");
    const b = new Uint8Array(p.length + v.length);
    b.set(p); b.set(v, p.length); push(out, b); return;
  }
  if (Array.isArray(v)) {
    push(out, Uint8Array.of(59));
    for (const x of v) enc(x, out);
    push(out, Uint8Array.of(TERM)); return;
  }
  if (typeof v === "object") {
    push(out, Uint8Array.of(60));
    for (const k of Object.keys(v)) { enc(k, out); enc(v[k], out); }
    push(out, Uint8Array.of(TERM)); return;
  }
  throw new Error("rencode: 编不了 " + typeof v);
}

export function rencode(v: any): Uint8Array {
  const parts: Uint8Array[] = [];
  enc(v, parts);
  let n = 0; for (const p of parts) n += p.length;
  const out = new Uint8Array(n);
  let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}
