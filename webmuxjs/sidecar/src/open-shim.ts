/**
 * `window.open` 的 features 过滤 —— **popup 一律变成 tab。**
 *
 * 带桌面的方案里 popup 是个独立窗口:不在 tab 条上、会盖住主窗口。
 * 这儿没有第二个窗口这种东西([f §5](../../../docs/v2/works/f-tabs.md#5-popup-不是特殊情况)),
 * 所以把 `width=`/`height=`/`left=` 那些吃掉,Chromium 就当普通 tab 开。
 *
 * **它不往回报任何东西** —— 唯一一个不碰 binding 的探针。
 * 新 tab 的事由 `Target.targetCreated` 说,页面这一侧无话可说。
 */

//: 留着这三个。它们不触发 popup,但**改变返回值语义** ——
//: `noopener` 必须还返回 `null`,吃掉它就改变了页面行为。
const KEEP = /^\s*(noopener|noreferrer|attributionsrc)\s*$/i;

export function install(): void {
  const native = window.open;
  window.open = function (
    this: unknown,
    url?: string | URL,
    name?: string,
    features?: string,
  ): Window | null {
    const keep = String(features || "")
      .split(",")
      .filter((f) => KEEP.test(f))
      .join(",");
    return native.call(this as Window, url, name, keep);
  };
  // 别让页面一眼看穿(有极少数站点靠 toString 判原生)
  try {
    window.open.toString = () => native.toString();
  } catch {
    /* 冻住了就算了,不值得为它放弃上面那一半 */
  }
}
