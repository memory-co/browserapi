import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import { UPSTREAM, allowed, ack, pickMode } from "../src/protocol/messages.ts";
import { mods, toFrame } from "../src/input/mods.ts";

const golden = JSON.parse(
  readFileSync(new URL("../fixtures/upstream.json", import.meta.url), "utf8"),
) as { types: string[]; modifiers: Record<string, number> };

describe("上行白名单", () => {
  it("和服务端那张表一字不差", () => {
    expect([...UPSTREAM].sort()).toEqual([...golden.types].sort());
  });

  it("表外的一律不放 —— 收口就是这张表本身", () => {
    for (const bad of ["eval", "navigate", "screenshot", "js", ""]) {
      expect(allowed({ type: bad }), bad).toBe(false);
    }
    expect(allowed(ack(1))).toBe(true);
    expect(allowed(pickMode("dom"))).toBe(true);
  });
});

describe("修饰键位", () => {
  it("和服务端那张表对得上", () => {
    expect(mods({ altKey: true })).toBe(golden.modifiers.Alt);
    expect(mods({ ctrlKey: true })).toBe(golden.modifiers.Control);
    expect(mods({ metaKey: true })).toBe(golden.modifiers.Meta);
    expect(mods({ shiftKey: true })).toBe(golden.modifiers.Shift);
  });

  it("是位,能叠加", () => {
    expect(mods({ ctrlKey: true, shiftKey: true })).toBe(2 | 8);
    expect(mods({})).toBe(0);
  });
});

describe("坐标换算", () => {
  it("元素被缩放过也要落在画面坐标上", () => {
    // 画面 1024×768,元素只有一半宽 —— 点元素中心该落在画面中心
    const p = toFrame({ x: 256, y: 192 },
                      { left: 0, top: 0, width: 512, height: 384 },
                      { w: 1024, h: 768 });
    expect(p).toEqual({ x: 512, y: 384 });
  });

  it("元素有偏移也算得对", () => {
    const p = toFrame({ x: 110, y: 220 },
                      { left: 10, top: 20, width: 100, height: 200 },
                      { w: 100, h: 200 });
    expect(p).toEqual({ x: 100, y: 200 });
  });
});
