# the_extension —— 那个扩展装上了没有,在不在干活

[`webmuxjs/extension/`](../../webmuxjs/extension/) 那棵树的落地验收。

## 判据一律取自浏览器那一侧

| 问什么 | 怎么问 |
| --- | --- |
| 装上了吗、跑起来了吗 | attach 到每个 `service_worker`,读它**自报家门**那个 `self.__wm_ext` |
| popup 变成 tab 了吗 | `Browser.getWindowForTarget` 给的 `windowId` 变没变 |
| 页面被碰过吗 | 页面里 `window.open` 还是不是 `[native code]`、`__wm_side` 在不在 |

**都不用"我们传了 `--load-extension`"当判据** —— 传了不等于装上了。

## 一个踩过的坑:MV3 的 service worker 是懒启动的

第一版这几条是**红的**,而扩展其实装得好好的 —— 浏览器一起来就去列 target,
那时候 SW 还没醒。

所以两件事:扩展要**自报家门**(不能靠文件名认它,浏览器自带的组件扩展里
也有叫 `sw.js` 的),而这儿要**等它报**,不是睡一个秒数。

## 为什么单开一个 chromium fixture

`chromium_endpoint` 是 session 级的、别处都在用 —— 给它加 `--load-extension`
等于**改所有用例跑在什么浏览器上**。而这儿要问的恰恰是"装了扩展会怎样",
所以它必须是自己那一个(`chromium_endpoint_with_extension`)。

## `attributionsrc` 那一条是故意放在里面的

它是 sidecar 那张白名单**放过去**的那个(已知的洞),而这个扩展接得住 ——
所以那一行同时是"扩展比 shim 严"的证据。
