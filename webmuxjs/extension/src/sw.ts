/**
 * **装进被控浏览器的那个扩展** —— service worker 是它的全部。
 *
 * 和 [`../../sidecar/`](../../sidecar/) 的分工:
 *
 * | | 跑在哪 | 干什么 |
 * | --- | --- | --- |
 * | sidecar | **被控页面里** | 改/看页面本身:光标、人在动没在动 |
 * | 这个 | **浏览器自己那一层** | 浏览器替我们做的那些事:窗口、tab |
 *
 * 判据是:**这件事要不要碰页面。** 不用碰的一律搬到这儿来 ——
 * 每搬一样,"探针改变了页面环境"那条代价就小一分
 * ([works/l](../../../docs/v2/works/l-extension.md))。
 *
 * ## MV3 的 service worker 会休眠
 *
 * 事件会把它唤醒,但**内存里的状态没了**。所以这儿只放"收到事件立刻处理完"
 * 的东西,不在里面攒状态。`popup-to-tab` 里那个 `main` 是个例外,
 * 而它丢了也自愈:下一个 `onCreated` 会把自己认成主窗口。
 */

import { install as popupToTab } from "./popup-to-tab.ts";

/**
 * **自报家门。**
 *
 * 认这个扩展不能靠"哪个 service worker 的文件名叫 sw.js" —— 浏览器自带的
 * 组件扩展里也有叫这个的。所以它在自己的全局上挂一个标记,
 * 谁想确认"装上了没有"就 attach 上来读它。
 *
 * **它同时是"活着没有"的判据**:MV3 的 service worker 是**懒启动**的,
 * 读得到这个标记意味着它真的跑起来了,而不只是被登记了。
 */
declare const self: { __wm_ext?: { version: string; parts: string[] } };

/** 装哪几样。**一个塌了不许带走其它的** —— 同 sidecar 那条规矩。 */
const PARTS: Array<[string, () => void]> = [["popup-to-tab", popupToTab]];

const ok: string[] = [];
for (const [name, fn] of PARTS) {
  try {
    fn();
    ok.push(name);
  } catch (e) {
    console.warn("[webmuxd] 扩展这一样没装上:" + name, e);
  }
}

// **装了哪几样也报出来** —— 少一样和整个没装上是两回事,
// 而"少一样"恰恰是那种不报错的坏。
self.__wm_ext = { version: "0.1.0", parts: ok };
