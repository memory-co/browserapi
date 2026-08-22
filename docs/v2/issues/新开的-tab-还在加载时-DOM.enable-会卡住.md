# 新开的 tab 还在加载时,`DOM.enable` 会卡住

**状态**:**已定位,未根治**(2026-08-22)。超时那一半修了(见 §3),
阻塞本身还在。

## 现象

`v2_cli_new_tab` / `v2_browser_new_tab` 偶发失败,而且只在**跑全量**的时候。
表现是一条普通命令挂满 30 秒然后回一串 urllib 的 traceback:

```console
$ webmuxd wait -t nt:1 --css a --timeout 30
  ✗ 退出码 1
    TimeoutError: timed out          ← 这不是我们说的话
```

## 是什么在卡

对着一个**刚被页面开出来、还在加载**的 tab,逐条量 attach 之后那几个调用:

```
Target.attachToTarget                      0.00s
DOM.enable                                 5.18s     ← 就是它
Page.enable                                0.00s
Runtime.enable                             0.00s
Runtime.addBinding                         0.00s
Page.addScriptToEvaluateOnNewDocument      0.00s
Accessibility.getFullAXTree                0.00s
```

**`DOM.enable` 要等那个渲染进程。** 空闲机器上 5 秒;跑全量的时候
一台机器上好几个 Chromium 加 xpra 加 Playwright,它就撞满 30 秒。

被测的那个页面是 news.baidu.com —— 挺重,这不是巧合。

## 为什么以前没定位到

因为**报出来的不是我们的错**:

`cdp.DEFAULT_TIMEOUT` 是 30 秒,而 SDK 那个 HTTP 客户端也是 30 秒。
一条 CDP 卡住的时候两边同时到点,**客户端总是先放弃** ——
于是人看到的是 urllib 的 traceback,里面一个字都没提 `DOM.enable`。

> **我们知道发生了什么,却没机会说。**

## 3. 修了的那一半:超时要分先后

客户端超时改成 60 秒(`api.Transport`)。服务端的预算(30 秒)必须**短于**
调用方的,否则我们的错误信息永远到不了人手上。

改完之后同样的卡住会变成:

```console
$ webmuxd wait -t nt:1 --css a
✗ timeout: …                    ← 我们的话,带着做到哪一步
```

顺带 5–18 秒那种"慢但会成功"的 attach 也不再被客户端提前掐死。

## 4. 没修的那一半:为什么要在 attach 的时候就 `DOM.enable`

现在 `Executor.start()` 一上来就 `DOM.enable` + `Page.enable`。
`DOM.enable` 是给后面 `DOM.getBoxModel` / `DOM.getNodeForLocation` 用的 ——
**但那是"用到的时候"才需要,不是 attach 的时候。**

几条路,都要先想清楚:

1. **推迟到第一次用。** 省掉大多数场景的等待,但把不确定性挪到了动作中间。
2. **给它一个短超时,失败就下次再来。** `DOM.enable` 是幂等的,重来无害;
   但"没 enable 就调 DOM.*"会报错,得有一条重试路径。
3. **先等那个 tab 加载完再 attach。** 最省事,但**这是替调用方做决定** ——
   人明明说了"现在对这个 tab 下命令"。

倾向 2:它不改变语义,只是不让一个还在忙的渲染进程把整条请求拖死。

## 5. 顺带看到的另一件

同一次量里冒出来一句:

```
没人放行这个 target,兜底放了(sid=…) —— 注入那条路没走到,画面里的探针可能是缺的
```

**页面自己开出来的 tab,走的不是我们那条 `waitForDebuggerOnStart` 的路。**
探针(光标、输入监听)可能是缺的。这条日志是对的 —— 它没有静默 ——
但**"可能是缺的"这句话本身说明我们没去确认**。另开一条。
