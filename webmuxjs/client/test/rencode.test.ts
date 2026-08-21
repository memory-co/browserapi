import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import { rdecode, rencode } from "../src/protocol/xpra/rencode.ts";
import { Framer, ProtocolError, frame } from "../src/protocol/xpra/packet.ts";

const golden = JSON.parse(
  readFileSync(new URL("../fixtures/rencode.json", import.meta.url), "utf8"),
) as { cases: { name: string; value: unknown; bytes: number[]; canonical: boolean }[] };

describe("rencodeplus", () => {
  it("表里每一串字节都解得出那个值 —— **解是精确的**", () => {
    for (const c of golden.cases) {
      expect(rdecode(new Uint8Array(c.bytes)), c.name).toEqual(c.value);
    }
  });

  it("编出来正好是那一串 —— 只对 canonical 那几条", () => {
    // 这个格式对同一个值允许多种表示(-1 可以是定长的 70,也可以是 int64)。
    // **我们只用显式的那几种**,不为省几个字节去挑最短表示。
    for (const c of golden.cases.filter((x) => x.canonical)) {
      expect([...rencode(c.value)], c.name).toEqual(c.bytes);
    }
  });

  it("非 canonical 的那些,编了再解也回得来", () => {
    for (const c of golden.cases.filter((x) => !x.canonical)) {
      expect(rdecode(rencode(c.value)), c.name).toEqual(c.value);
    }
  });

  it("编了再解还是原来那个", () => {
    for (const v of [0, 43, -1, 1234567, 3.5, "", "中文", true, false, null,
                     [1, "a", [2]], { a: 1, b: [true, null] }]) {
      expect(rdecode(rencode(v))).toEqual(v);
    }
  });
});

describe("xpra 的 8 字节头", () => {
  const body = new Uint8Array([0x43, 0x41]);   // 随便两个字节

  it("上行头是大端 —— 和我们自己那个 28 字节头的小端相反", () => {
    const f = frame(new Uint8Array(0x0102));
    expect(f[0]).toBe(0x50);                   // 'P'
    expect([f[4], f[5], f[6], f[7]]).toEqual([0, 0, 0x01, 0x02]);
  });

  it("一条 WS 消息拆成几段送进来也拼得回一个包", () => {
    const one = frame(rencode(["ping", 1]));
    const fr = new Framer();
    expect(fr.feed(one.subarray(0, 3))).toEqual([]);     // 头都没齐
    expect(fr.feed(one.subarray(3, 9))).toEqual([]);     // body 没齐
    expect(fr.feed(one.subarray(9))).toEqual([["ping", 1]]);
  });

  it("一段里有两个包就吐两个", () => {
    const a = frame(rencode(["ping", 1])), b = frame(rencode(["ping", 2]));
    const both = new Uint8Array(a.length + b.length);
    both.set(a); both.set(b, a.length);
    expect(new Framer().feed(both)).toEqual([["ping", 1], ["ping", 2]]);
  });

  it("裸字节 chunk 会挂到包上", () => {
    const px = new Uint8Array([9, 9, 9]);
    const chunk = new Uint8Array(8 + px.length);
    chunk[0] = 0x50; chunk[1] = 0x10; chunk[2] = 0; chunk[3] = 1;   // index=1
    new DataView(chunk.buffer).setUint32(4, px.length);
    chunk.set(px, 8);
    const main = frame(rencode(["draw", 1]));
    const fr = new Framer();
    expect(fr.feed(chunk)).toEqual([]);          // chunk 自己不成包
    const [p] = fr.feed(main);
    expect(p![1]).toEqual(px);                   // 挂在下标 1 上
  });

  it("**不静默降级**:下行带压缩就报错,不是悄悄丢掉", () => {
    const bad = frame(body);
    bad[2] = 1;                                  // level=1
    expect(() => new Framer().feed(bad)).toThrow(ProtocolError);
  });

  it("第一个字节不是 'P' 也报错", () => {
    const bad = frame(body);
    bad[0] = 0x51;
    expect(() => new Framer().feed(bad)).toThrow(ProtocolError);
  });
});
