/**
 * **popup 一律变成 tab** —— 而且**一个字都不注进页面**。
 *
 * 这儿没有第二个窗口这种东西([f §5](../../../docs/v2/works/f-tabs.md#5-popup-不是特殊情况)):
 * popup 不在那条外挂 bar 上;JPG 那条腿 screencast 只挂一个 target;
 * VNC 那条腿画面是整个 X 桌面,第二个窗口会**盖在 kiosk 窗口上**。
 *
 * ## 和 sidecar 里那个 `open-shim` 的差别
 *
 * 那个的做法是**改页面的 `window.open`,按一张白名单过滤 features**。
 * 这个的做法是**等它开出来,再搬回主窗口**。三处不一样,都不是小事:
 *
 * 1. **不碰页面。** 没有 `window.open` 补丁、没有伪造 `toString`,
 *    [b §6](../../../docs/v2/works/b-input.md) 那条"探针页面看得见"的
 *    代价在这一样上没有了。
 * 2. **不需要白名单,所以没有那个洞。** 白名单必然有"少列了一个词"的失败,
 *    而它真的漏过:`attributionsrc` 在 `KEEP` 里留着,实测**照样开出真窗口**。
 *    这儿**从不解析 features 串** —— Chromium 爱怎么判怎么判,我们只管搬。
 * 3. **语义自动保住。** `noopener` 仍然返回 `null`,因为那是 Chromium 自己
 *    算的,我们没插手;`open-shim` 要靠一条正则**记得**把它留下。
 *
 * ## 一条真代价
 *
 * 那个 popup 窗口是**真的被创建了**,然后才被搬走。无头下看不出来;
 * **有头(VNC)那条腿上它可能闪一下** —— 那是一个真的 X 窗口。
 *
 * 实测搬完之后 opener 关系完好:opener 手里那个句柄 `closed === false`、
 * 能写子页的 `document`、`postMessage` 发得出;子页 `window.opener` 仍在。
 */

/** 主窗口 —— **第一个见到的那个**。kiosk / headless 下只会有一个。 */
let main: number | null = null;

export function install(): void {
  chrome.windows.getAll({}, (ws) => {
    if (main === null && ws.length && ws[0]) main = ws[0].id ?? null;
  });

  chrome.tabs.onCreated.addListener((tab) => {
    if (main === null) {
      main = tab.windowId;      // 还没认出主窗口,那这个就是
      return;
    }
    if (tab.windowId === main || tab.id === undefined) return;
    // **搬回来。** 失败不重试:搬不动说明那个 tab 已经没了,
    // 而"没了"不需要我们做任何事。
    chrome.tabs.move(tab.id, { windowId: main, index: -1 }, () => {
      void chrome.runtime.lastError;
    });
  });
}
