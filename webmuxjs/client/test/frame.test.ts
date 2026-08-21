import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import {
  HEADER_SIZE, buildHeader, packTarget, parseHeader, shouldDrop,
} from "../src/protocol/frame.ts";

/** 和 Python 那侧共用的 golden —— **任何一边改了格式,两边一起红。** */
const golden = JSON.parse(
  readFileSync(new URL("../fixtures/frame-header.json", import.meta.url), "utf8"),
) as { cases: { cast: number; frame: number; target: string; bytes: number[] }[] };

describe("28 字节头", () => {
  it("和 Python 编出来的字节一模一样", () => {
    for (const c of golden.cases) {
      const got = [...buildHeader({
        castSessionId: c.cast, frameId: c.frame, targetId: c.target,
      })];
      expect(got, `cast=${c.cast} target=${c.target}`).toEqual(c.bytes);
    }
  });

  it("解 Python 编的,也解得回去", () => {
    for (const c of golden.cases) {
      const h = parseHeader(new Uint8Array(c.bytes));
      expect(h.castSessionId).toBe(c.cast);
      expect(h.frameId).toBe(c.frame);
      if (!/^[0-9a-f]*$/i.test(c.target)) continue;   // 不是 hex 的下面单独说
      // 短的 targetId 两边都补零,解出来是补零之后那个
      expect(h.targetId).toBe(c.target.padEnd(32, "0").slice(0, 32).toLowerCase());
    }
  });

  it("不是 hex 的 targetId,两边一样地当成零 —— 一致比正确更要紧", () => {
    const c = golden.cases.find((x) => !/^[0-9a-f]*$/i.test(x.target))!;
    expect(parseHeader(new Uint8Array(c.bytes)).targetId).toBe("0".repeat(32));
  });

  it("头是定长的 —— 奇怪的 targetId 也不许让流错位", () => {
    for (const weird of ["", "zz", "x".repeat(80), "не-hex"]) {
      expect(buildHeader({ castSessionId: 1, frameId: 1, targetId: weird })
        .byteLength).toBe(HEADER_SIZE);
    }
  });

  it("解不动的 hex 当零,而不是 NaN", () => {
    expect(packTarget("zzzzzzzz".repeat(4))).toEqual([0, 0, 0, 0]);
  });

  it("不足 28 字节要抛,不要静默给个半截头", () => {
    expect(() => parseHeader(new Uint8Array(27))).toThrow();
  });
});

describe("丢帧规则", () => {
  const h = (cast: number, target: string) =>
    ({ castSessionId: cast, frameId: 1, targetId: target });

  it("上一轮 startScreencast 的残帧要丢", () => {
    expect(shouldDrop(h(3, "aa"), 5, "")).toBe(true);
    expect(shouldDrop(h(5, "aa"), 5, "")).toBe(false);
    expect(shouldDrop(h(7, "aa"), 5, "")).toBe(false);
  });

  it("切 tab 之后管道里旧 tab 的帧要丢", () => {
    expect(shouldDrop(h(5, "aa"), 5, "bb")).toBe(true);
    expect(shouldDrop(h(5, "bb"), 5, "bb")).toBe(false);
  });

  it("还不知道基准的时候一律收下 —— 否则第一帧永远进不来", () => {
    expect(shouldDrop(h(1, "aa"), 0, "")).toBe(false);
  });
});
