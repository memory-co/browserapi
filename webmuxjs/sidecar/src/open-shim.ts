/**
 * `window.open` 的 features 过滤 —— **popup 一律变成 tab。**
 *
 * 带桌面的方案里 popup 是个独立窗口:不在 tab 条上、会盖住主窗口。
 * 这儿没有第二个窗口这种东西([f §5](../../../docs/v2/works/f-tabs.md#5-popup-不是特殊情况)),
 * 所以把 `width=`/`height=`/`left=` 那些吃掉,Chromium 就当普通 tab 开。
 *
 * **它不往回报任何东西** —— 唯一一个不碰 binding 的探针。
 * 新 tab 的事由 `Target.targetCreated` 说,页面这一侧无话可说。
 *
 * ---
 *
 * ## ⚠ 这一样正在被替代 —— [`webmuxjs/extension/src/popup-to-tab.ts`](../../extension/src/popup-to-tab.ts)
 *
 * 那边的做法是**等 popup 开出来再 `chrome.tabs.move` 搬回主窗口**,
 * 三处比这儿强([works/l §5.1](../../../docs/v2/works/l-extension.md)):
 *
 * 1. **不碰页面** —— 没有 `window.open` 补丁、没有伪造 `toString`
 * 2. **不需要白名单,所以没有下面那个洞**(见 `KEEP` 上面那段)
 * 3. **`noopener` 的 `null` 自动保住** —— 那是 Chromium 自己算的,没人插手
 *
 * **两套并存是安全的,而且比任何一边单独都严**:这儿先把 features 过滤掉,
 * 于是根本不会开出 popup,那边就成了空操作;唯一两边不一致的是
 * `attributionsrc` —— 这儿放它过去,那边接得住。
 *
 * **等下一版发出去、验完功能完全等同,删掉这一样。**
 */

//: 留着这三个。前两个**改变返回值语义** —— `noopener` 必须还返回 `null`,
//: 吃掉它就改变了页面行为。
//:
//: ⚠ **第三个是个洞。** 注释原来写的是"它们不触发 popup",而实测
//: (Chromium 152)`window.open(u, n, "attributionsrc")` **照样开出真窗口** ——
//: Chromium 判 popup 的规则是"去掉 `noopener`/`noreferrer` 之后还剩东西吗",
//: 而 `attributionsrc` 不在豁免名单里。
//:
//: **这个洞不在这儿补**:补它要在"保住归因语义"和"一律变成 tab"之间二选一,
//: 而扩展那条路两样都不用选(它从不解析这个串)。
//: 见 [`../../extension/src/popup-to-tab.ts`](../../extension/src/popup-to-tab.ts)。
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
