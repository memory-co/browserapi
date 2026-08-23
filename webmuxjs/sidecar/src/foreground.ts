/**
 * **这一页是不是浏览器的前台** —— 这一条是补一个 CDP 的窟窿。
 *
 * `active`(当前是哪个 tab)是整张 tab 表里**唯一一个没有观测支撑**的字段:
 * CDP 没有「tab 被激活了」这种事件,所以原来的做法是"我们记一个字段,
 * 再用 `Target.activateTarget` 把浏览器拽过来对齐"。
 *
 * 那个做法默认了**只有我们会动前台**。不是的:
 *
 * > 页面 `window.open` / `<a target=_blank>` 开出来的 tab,
 * > **Chromium 直接把前台切过去,而且不发任何事件。**
 *
 * 漂了之后两条腿各错各的、**都不报错**:VNC 上人看到的是新那页而 tab 条、
 * 地址栏、不带下标的命令全指着旧那页;JPG 上截屏还挂在一个后台 target 上,
 * 画面冻在最后一帧,看着还挺一致。
 * (`docs/v2/works/f-tabs.md` §3.1 记着这件事,那儿原来写着"漂移在物理上不可能"。)
 *
 * `document.visibilityState` 是标准的、页面自己就知道的,DevTools 连上去
 * 读到的是同一个值。把它报上来,「浏览器换前台了」就从一件猜不到的事
 * 变成了一条真事件。
 *
 * **两个方向都报。** 只报"我变前台了"的话,判据就压在**新那个 tab 装没装上
 * 探针**上 —— 而 `about:blank`、没加载完的、注入失败的页都装不上。
 * 加上"我不是前台了",在我们**本来就盯着的那个 tab** 上也能发现同一件事。
 * 两个探测器,任一个响都够。
 */

import type { Send } from "./wire.ts";

export function install(send: Send): void {
  // **只有顶层报。** `visibilityState` 在 iframe 里跟着顶层文档走,
  // 每个 frame 报一遍就是同一件事说 N 遍。
  try {
    if (window.top !== window) return;
  } catch {
    return; // 跨源拿不到 top —— 那就更不是顶层
  }

  let last: boolean | null = null;
  const report = (): void => {
    const on = document.visibilityState === "visible";
    if (on === last) return; // 变了才报
    last = on;
    send("foreground", { on });
  };

  document.addEventListener("visibilitychange", report, true);
  // 装上那一刻的事实也算一条 —— 导航之后这段会重跑,而**导航本身
  // 就是前台最容易被换掉的时刻**。
  report();
}
