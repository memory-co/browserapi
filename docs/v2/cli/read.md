# cli · 读

```bash
webmuxd capture -t demo             # 正文
webmuxd capture -t demo --shot p.webp   # 那一刻的页面
webmuxd url     -t demo
webmuxd status  -t demo
```

**读只有两样:一张图,和正文。** 对应 tmux 的 `capture-pane` ——
这是形态那条([README](README.md#三条对齐))决定的。

## 1. `snapshot` —— 这一条要先想清楚

agent-browser 的核心工作流是:

```
snapshot  →  拿到带 ref 的可访问性树(@e1 @e2 …)
click @e1 →  照 ref 操作,不用再查 DOM
```

**我们曾经有过这个,砍了**([i §3](../works/i-agent-surface.md#3-读的那一面一张图和正文))。
理由是:那是一套**关于 agent 该怎么用浏览器的意见** ——
150 个上限、"可交互优先"那张 role 表、编号的稳定性保证 ——
每一条都是会被将来的模型推翻的赌注。

**但 agent-browser 证明了另一种活法**,而且它把赌注下得更小:

| | 我们砍掉的那个 | agent-browser |
| --- | --- | --- |
| 编号 | `[12]`,**只在一次观测里成立** | `@e1`,**daemon 里存着**,跨命令有效 |
| 过期 | 靠 `observation` id 挡 | 页面变了 ref 失效,直接报错 |
| 筛选 | 上限 150,规则写死在库里 | `-i` 只要可交互、`-c` 压缩、`-d` 限深、`-s` 限范围 —— **调用方说了算** |

**差别在"意见留在哪"**:我们把筛选规则做成了库的决定;
它把参数交出去了。**后者不违反那条判据。**

🔲 **待讨论,三个问题:**

1. **要不要 ref?** 我们现在是"按人看得见的字定位",没有 ref 也能干活
   ([act.md](act.md))。ref 买到的是**确定性**(同一个 ref 一定是同一个元素),
   代价是 daemon 里要存一份表,而那份表会过期
2. **如果要,存在哪?** session 里(`Server` 现在就持有全部 session,有地方放)
3. **`--annotate` 呢?** agent-browser 的 `screenshot --annotate` 在图上画编号。
   我们也砍过([issue](../issues/标注层会被人看见.md))—— 但砍的理由是
   **它画在活页面上**,不是"不该有这个功能"。**在图上画**是另一回事,
   代价是服务端要能画图(今天只有 websockets + aiohttp 两个依赖)

## 2. `get` 那一族

agent-browser:`get text|html|value|attr|title|url|count|box|styles <sel>`、
`is visible|enabled|checked <sel>`。

我们:后端有 `extract`(`text` / `html` / `table` / `attr` 四种模式),
CLI 没暴露 —— 见 [act.md](act.md) 那张待做表。

🔲 **待讨论:`is` 那一族。** `is visible` / `is enabled` 的信息后端**有**
(元素表里就带着 `in_viewport` / `enabled`),但那张表不对外。
要给的话,是给一个"问一个元素的状态"的口子,而不是把整张表倒出去。

## 3. `capture` 的两个形状

```console
$ webmuxd capture -t demo | head -3        # 正文,对应 capture-pane -p
$ webmuxd capture -t demo --shot p.webp    # 那一刻的页面
✓ 存到 p.webp
```

**WebP 不是 PNG** —— 同样画质小一半,而这条流量要走网络。

🔲 **待讨论:`--full`(整页)。** 后端有(`full_page=true`),CLI 没给。
`pdf` 后端也没有。
