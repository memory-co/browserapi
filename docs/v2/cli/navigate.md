# cli · 导航

**这一层照普通浏览器,而且 agent-browser 也是同一套词** —— 三条对齐在这儿完全重合。

```bash
webmuxd goto    -t demo https://example.com
webmuxd back    -t demo
webmuxd forward -t demo
webmuxd reload  -t demo
webmuxd stop    -t demo
webmuxd url     -t demo
webmuxd wait    -t demo [--text T] [--css SEL] [--url-contains S] [--timeout 秒]
```

## 1. `goto` 只导航,不起浏览器

agent-browser 的 `open [url]` **会顺手把浏览器起起来**(daemon 自启)。
我们不这么做:起会话是 `new`,导航是 `goto`。

> **一个命令一件事。** 这是[形态那条](README.md#三条对齐)要的 ——
> tmux 的 `new-window` 和 `send-keys` 是两件事,没有一个命令"顺手开个窗口再敲字"。
>
> 代价是多打一行;买到的是**报错指得准**:起不来是起不来,导航失败是导航失败。

`goto` 会拦特权地址:`chrome://` `devtools://` `chrome-extension://` `view-source:`
一律拒绝 —— **不是做不到,是不该做**。

### 说了 http 就是 http

新版 Chrome 默认开着 **HTTPS-First(Balanced Mode)**:你请求 `http://`,
它先替你换成 `https://` 试,失败就停在一张
「This site doesn't support a secure connection」上。

**我们把它关了**([`processes.BASE_ARGS`](../../../webmuxd/processes.py)),
`webmuxd info` 里报着这一行。

> **这是关掉一个安全特性,所以要说出来。** 判据是这个项目那条老规矩:
> **显式传入优先** —— 和「端口由你给」同一条。调用方写了 `http://`,
> 替它改成别的,就是替它改了它说的话。

而且不关的话那条路是**封死的**,不是"少一个选项":那张 interstitial
从我们这边看是**空文档** —— `certificateErrorPageController` 是空壳、
`document.body` 长度 0、AX 树空,**有头无头一样**。
人在画面里看得见那两个按钮、点得动;我们够不着。
(`kill-tab` 之类的"退出去"还能做,但"进去"做不了。)

站点自己 301 到 https 不受影响 —— 那是站点的决定,不是浏览器替谁做的。

## 1.5 打不开的时候

```console
$ webmuxd goto -t demo http://nonexistent.invalid/
✗ nav_failed: http://nonexistent.invalid/ 打不开:net::ERR_NAME_NOT_RESOLVED
  域名解析不了 —— 地址打错了,还是这台机器没有 DNS?
```

退出码 **8**。`Page.navigate` 的 `errorText` 一直在,只是以前被扔掉了 ——
于是打不开的站会打一个 ✓,`url` 还显示成目标地址(Chrome 的错误页保留原地址),
而 `capture` 是空的。**对 agent 就是"什么都没发生,而且不报错"。**

**光看 `url` 判断不出成没成** —— 唯一可靠的是退出码。

## 2. `wait` 等的是**那件事**,不是一个秒数

```bash
webmuxd wait -t demo --url-contains "s?wd="     # 地址变了
webmuxd wait -t demo --text "搜索结果"           # 字出来了
webmuxd wait -t demo --css "#results"           # 元素出来了
```

**睡固定时长是在赌网速** —— 赌输了就是一条时灵时不灵的脚本,而那比没有更坏。
[v2_cli_simple](../../../tests/v2_cli_simple/) 里就是这么用的。

对得上 agent-browser 的 `wait <selector>` / `--text` / `--url`。

🔲 **待讨论:`wait <ms>` 和 `wait --load networkidle`。**
- 纯等毫秒:故意没给 —— 见上面那句。但 `sleep 2 && webmuxd …` 谁都会写,
  给不给其实不改变什么,**可以给**
- `--load networkidle`:后端**已经有**(`settle.strategy`,每个动作后都在用),
  只是没作为独立命令暴露出来

🔲 **待讨论:`pushstate <url>`。** SPA 的客户端跳转。后端没有对应动词 ——
今天只能 `send` 一段 `history.pushState`。

## 3. `url` 和 `status`

```console
$ webmuxd url -t demo
https://www.baidu.com/s?wd=webmuxd

$ webmuxd status -t demo
```

`get title` / `get cdp-url` 那几个 agent-browser 有的,见 [read.md](read.md)。
