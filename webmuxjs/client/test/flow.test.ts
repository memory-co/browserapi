import { describe, expect, it, vi } from "vitest";

import { Acker } from "../src/flow/ack.ts";
import { Batcher } from "../src/flow/batch.ts";
import type { Upstream } from "../src/protocol/messages.ts";

/** 手动跑的假定时器 —— 这两层的行为全是"时间到了做什么"。 */
function fakeTimers() {
  let next = 1;
  const jobs = new Map<number, () => void>();
  return {
    set: (fn: () => void, _ms: number) => { jobs.set(next, fn); return next++; },
    clear: (h: unknown) => { jobs.delete(h as number); },
    /** 把当前挂着的都跑一遍。 */
    tick() {
      const now = [...jobs.entries()];
      jobs.clear();
      for (const [, fn] of now) fn();
    },
    pending: () => jobs.size,
  };
}

describe("环 B:回执", () => {
  it("收到一帧立刻回,带帧号", () => {
    const sent: Upstream[] = [];
    const t = fakeTimers();
    const a = new Acker((m) => sent.push(m), t.set, t.clear);
    a.got(7);
    expect(sent).toEqual([{ type: "ack", frameId: 7 }]);
  });

  it("丢了一帧也能自愈 —— 心跳补发最后那个帧号", () => {
    const sent: Upstream[] = [];
    const t = fakeTimers();
    const a = new Acker((m) => sent.push(m), t.set, t.clear);
    a.got(7);
    t.tick();                       // 3 秒到了,后面再没来帧
    t.tick();
    expect(sent).toEqual([
      { type: "ack", frameId: 7 },
      { type: "ack", frameId: 7 },
      { type: "ack", frameId: 7 },
    ]);
  });

  it("新帧来了就把心跳往后推,不重复补发旧的", () => {
    const sent: Upstream[] = [];
    const t = fakeTimers();
    const a = new Acker((m) => sent.push(m), t.set, t.clear);
    a.got(1);
    a.got(2);
    t.tick();
    expect(sent.map((m) => (m as { frameId: number }).frameId)).toEqual([1, 2, 2]);
  });

  it("断了要停 —— 否则重连之后打在旧连接上", () => {
    const t = fakeTimers();
    const a = new Acker(() => {}, t.set, t.clear);
    a.got(1);
    expect(t.pending()).toBe(1);
    a.stop();
    expect(t.pending()).toBe(0);
  });
});

describe("输入聚批", () => {
  const move = (x: number): Upstream =>
    ({ type: "mouse", event: "move", x, y: 0, modifiers: 0 });
  const wheel = (dy: number): Upstream =>
    ({ type: "wheel", x: 0, y: 0, dx: 0, dy, modifiers: 0 });

  it("同一批里只留最后一个 move", () => {
    const sent: Upstream[] = [];
    const t = fakeTimers();
    const b = new Batcher((m) => sent.push(m), t.set);
    b.queue(move(1)); b.queue(move(2)); b.queue(move(3));
    expect(sent).toEqual([]);            // 还没到点,一个都没发
    t.tick();
    expect(sent).toEqual([move(3)]);
  });

  it("滚轮要累加,不能只留最后一个 —— 丢掉的每一格都是真滚过的距离", () => {
    const sent: Upstream[] = [];
    const t = fakeTimers();
    const b = new Batcher((m) => sent.push(m), t.set);
    b.queue(wheel(10)); b.queue(wheel(20)); b.queue(wheel(5));
    t.tick();
    expect(sent).toEqual([{ type: "wheel", x: 0, y: 0, dx: 0, dy: 35, modifiers: 0 }]);
  });

  it("按下、抬起、按键不进批", () => {
    const sent: Upstream[] = [];
    const t = fakeTimers();
    const b = new Batcher((m) => sent.push(m), t.set);
    const down: Upstream = { type: "mouse", event: "down", x: 1, y: 1, modifiers: 0 };
    b.queue(down);
    expect(sent).toEqual([down]);        // 立刻走
    expect(t.pending()).toBe(0);
  });

  it("按下之前先把攒着的位置发掉,否则远端收到的是上一个采样点", () => {
    const sent: Upstream[] = [];
    const t = fakeTimers();
    const b = new Batcher((m) => sent.push(m), t.set);
    b.queue(move(9));
    const down: Upstream = { type: "mouse", event: "down", x: 9, y: 0, modifiers: 0 };
    b.now(down);
    expect(sent).toEqual([move(9), down]);
  });
});

describe("默认定时器", () => {
  // **这一条是真浏览器抓出来的,不是想出来的。**
  //
  // 原来两个构造函数里写的是 `setTimer = setTimeout as ...`。传进来之后
  // 它被当成这个对象的方法调用,而浏览器要求 `setTimeout` 的接收者是
  // `window` —— 于是每收一帧抛一次 `Illegal invocation`,环 B 整个死掉,
  // 服务端额度耗尽就再也不推帧了。
  //
  // 上面所有用例都喂假定时器,**所以一条都没碰到这条路**。

  it("Acker 不传定时器也能用", () => {
    const sent: Upstream[] = [];
    const a = new Acker((m) => sent.push(m));
    expect(() => a.got(1)).not.toThrow();
    expect(sent).toEqual([{ type: "ack", frameId: 1 }]);
    a.stop();
  });

  it("Batcher 不传定时器也能用", async () => {
    const sent: Upstream[] = [];
    const b = new Batcher((m) => sent.push(m), undefined, 1);
    expect(() => b.queue({ type: "mouse", event: "move", x: 1, y: 1, modifiers: 0 }))
      .not.toThrow();
    await new Promise((r) => setTimeout(r, 20));
    expect(sent).toHaveLength(1);
  });
});
