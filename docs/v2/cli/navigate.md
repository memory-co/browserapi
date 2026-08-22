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
