# extension —— 装进被控浏览器的那个扩展

和 [`../sidecar/`](../sidecar/) 平级,分工的判据只有一条:

> **这件事要不要碰页面。**

| | 跑在哪 | 干什么 |
| --- | --- | --- |
| [`sidecar`](../sidecar/) | **被控页面里** | 改/看页面本身:光标、人在动没在动 |
| 这儿 | **浏览器自己那一层** | 浏览器替我们做的那些事:窗口、tab |

不用碰页面的一律往这边搬。**每搬一样,"探针改变了页面环境"那条代价就小一分**
([b §6](../../docs/v2/works/b-input.md) · [works/l](../../docs/v2/works/l-extension.md))。

```
npm install
npm run build     # → dist/(manifest.json + sw.js),打包时拷进 webmuxd/_extension/
npm test
npm run typecheck
```

## 今天装了一样

[`popup-to-tab.ts`](src/popup-to-tab.ts) —— **popup 一律变成 tab,
而且一个字都不注进页面**:等 Chromium 把那个窗口开出来,再
`chrome.tabs.move` 搬回主窗口。

它替代 sidecar 里那个 `open-shim`,三处更强(实测,Chromium 152):

| 页面调的 | `open-shim` | 这儿 |
| --- | --- | --- |
| `width=400,height=300,left=10` | tab | **tab** |
| `popup=1` | tab | **tab** |
| `noopener,width=400` | tab,返回 `null` | **tab**,返回 `null` |
| **`attributionsrc`** | **POPUP** ⚠ 白名单放它过去了 | **tab** |

1. **不碰页面** —— 没有 `window.open` 补丁、没有伪造 `toString`
2. **不需要白名单,所以没有那个洞** —— 白名单必然有"少列了一个词"的失败,
   而它真的漏过。这儿**从不解析 features 串**
3. **`noopener` 的 `null` 自动保住** —— 那是 Chromium 自己算的,我们没插手

**一条真代价**:那个 popup 窗口是**真的被创建了**再被搬走。
无头下看不出来;**有头(VNC)那条腿上它可能闪一下** —— 那是一个真的 X 窗口。
这一条**还没在有头下实测过**。

## 三条这儿特有的规矩

**① 权限面要小,而且看得住。** 今天只有 `"permissions": ["tabs"]` ——
**没有 `host_permissions`、没有内容脚本**。多一条都要有人解释得清为什么,
[`tests/the_extension/`](../../tests/the_extension/) 盯着这三样。

**② service worker 会休眠,所以不在里面攒状态。** MV3 的 SW 被事件唤醒,
但内存里的东西没了。`popup-to-tab` 里那个 `main` 是唯一的例外,
而它丢了也自愈:下一个 `onCreated` 会把自己认成主窗口。

**③ 它要自报家门。** `self.__wm_ext = { version, parts }`。
认这个扩展**不能靠文件名**(浏览器自带的组件扩展里也有叫 `sw.js` 的),
也不能靠"我们传了 `--load-extension`"(传了不等于装上了)。
而且 MV3 的 SW 是懒启动的 —— **读得到这个标记才意味着它真的跑起来了**。

## 产物是一个目录,不是一个文件

`--load-extension=` 只收目录。这是它和 sidecar 在打包上唯一的实质差别
(那边是一段源码,`Runtime.evaluate` 直接丢进去就行)。
