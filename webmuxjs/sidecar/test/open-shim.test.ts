/**
 * popup → tab:**吃掉尺寸,留住语义。**
 *
 * 这两半分开看都像小事,合起来才是那条规矩:吃多了会改变页面行为
 * (`noopener` 必须还返回 `null`),吃少了就冒出一个我们这儿根本
 * 不存在的第二个窗口。
 */

import { describe, expect, it, vi } from "vitest";
import { install } from "../src/open-shim.ts";

describe("window.open", () => {
  it("尺寸位置那些一律吃掉,`noopener` 那三个留着", () => {
    const native = vi.fn(() => null);
    const real = window.open;
    window.open = native as unknown as typeof window.open;
    try {
      install();
      window.open("/x", "_blank", "width=400,height=300,left=10,noopener,noreferrer");
      expect(native).toHaveBeenCalledWith("/x", "_blank", "noopener,noreferrer");
    } finally {
      window.open = real;
    }
  });

  it("本来就没 features,也不会凭空多出来", () => {
    const native = vi.fn(() => null);
    const real = window.open;
    window.open = native as unknown as typeof window.open;
    try {
      install();
      window.open("/x");
      expect(native).toHaveBeenCalledWith("/x", undefined, "");
    } finally {
      window.open = real;
    }
  });

  it("toString 还装得像原生 —— 有站点靠它判", () => {
    const real = window.open;
    try {
      install();
      expect(String(window.open)).toBe(String(real));
    } finally {
      window.open = real;
    }
  });
});
