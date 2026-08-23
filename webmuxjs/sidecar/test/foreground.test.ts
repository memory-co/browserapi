/**
 * 「浏览器换前台了」这条事件本身。
 *
 * 端到端那几条验的是**结果**(浏览器前台和我们那张表对不对得上);
 * 这儿验的是**这段代码在什么时候开口** —— 而它最容易错的两处恰恰
 * 端到端看不见:iframe 里也报一遍、没变也一直报。
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { install } from "../src/foreground.ts";

function visibility(state: DocumentVisibilityState): void {
  Object.defineProperty(document, "visibilityState", {
    value: state,
    configurable: true,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("前台变了", () => {
  beforeEach(() => {
    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      configurable: true,
    });
  });

  it("装上那一刻就报一条 —— 导航正是前台最容易被换掉的时刻", () => {
    const send = vi.fn();
    install(send);
    expect(send).toHaveBeenCalledWith("foreground", { on: true });
  });

  it("两个方向都报", () => {
    const send = vi.fn();
    install(send);
    send.mockClear();

    visibility("hidden");
    expect(send).toHaveBeenCalledWith("foreground", { on: false });

    send.mockClear();
    visibility("visible");
    expect(send).toHaveBeenCalledWith("foreground", { on: true });
  });

  it("**没变就不报**", () => {
    const send = vi.fn();
    install(send);
    send.mockClear();

    visibility("visible");
    visibility("visible");
    expect(send).not.toHaveBeenCalled();
  });

  it("iframe 里一声不吭 —— 同一件事不该说 N 遍", () => {
    const send = vi.fn();
    const real = window.top;
    Object.defineProperty(window, "top", { value: {}, configurable: true });
    try {
      install(send);
      visibility("hidden");
      expect(send).not.toHaveBeenCalled();
    } finally {
      Object.defineProperty(window, "top", { value: real, configurable: true });
    }
  });
});
