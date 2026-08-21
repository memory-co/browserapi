import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";

import { normalizeUrl } from "../src/viewer/tabs.ts";
import { aligned, effectiveZoom, replayScale } from "../src/screen/fit.ts";

describe("地址栏那一串", () => {
  it("有 scheme 就原样走", () => {
    expect(normalizeUrl("https://a.com")).toBe("https://a.com");
    expect(normalizeUrl("about:blank")).toBe("about:blank");
  });

  it("像域名就补 https", () => {
    expect(normalizeUrl("example.com")).toBe("https://example.com");
  });

  it("带空格的是搜索词,不是网址 —— 当网址打开会得到一个莫名其妙的 404", () => {
    expect(normalizeUrl("怎么 装 xpra")).toContain("google.com/search?q=");
    expect(normalizeUrl("hello world")).toContain("search?q=");
  });
});

describe("有效缩放", () => {
  it("1.00x 才是像素级对齐", () => {
    expect(effectiveZoom(1024, 1, 1024)).toBe(1);
    expect(aligned(1)).toBe(true);
  });

  it("dsf=2 的帧显示在 dpr=1 的屏上就是 0.5x", () => {
    expect(effectiveZoom(1024, 1, 2048)).toBe(0.5);
    expect(aligned(0.5)).toBe(false);
  });

  it("还没解码出帧尺寸的时候不瞎算", () => {
    expect(effectiveZoom(1024, 1, 0)).toBe(0);
    expect(replayScale(800, 0)).toBe(1);
  });
});

describe("那条通道结构上没有上行", () => {
  it("rrweb.ts 里没有发送函数 —— 不是发之前判断一下", () => {
    const src = readFileSync(new URL("../src/channel/rrweb.ts", import.meta.url), "utf8");
    const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*/g, "");
    expect(code).not.toMatch(/\.send\s*\(/);
  });
});

describe("三条腿互不认识", () => {
  const dir = new URL("../src/channel/", import.meta.url);
  it("一条通道一个文件,谁也不 import 谁", () => {
    const legs = readdirSync(dir).filter((f: string) => f.endsWith(".ts"));
    expect(legs.sort()).toEqual(["cdp.ts", "rrweb.ts", "xpra.ts"]);
    for (const f of legs) {
      const src = readFileSync(new URL(f, dir), "utf8");
      for (const other of legs) {
        if (other === f) continue;
        expect(src, `${f} 不该 import ${other}`)
          .not.toContain(`./${other.replace(".ts", "")}`);
      }
    }
  });
});
