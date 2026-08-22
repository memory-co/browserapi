# cli · 读

```bash
webmuxd snapshot -t demo [-i] [-s CSS] [--viewport] [--max N]   # 这页上有什么
webmuxd capture  -t demo                # 正文
webmuxd capture  -t demo --shot p.webp  # 那一刻的页面
webmuxd url      -t demo
webmuxd status   -t demo
```

**读是三样:一张元素表、正文、一张图。** 对应 tmux 的 `capture-pane` ——
"把里面的东西抓出来",三种粒度而已。

## 1. `snapshot` —— 这一页上有什么

```bash
webmuxd snapshot -t demo             # 全部:能点的 + 有名字的结构
webmuxd snapshot -t demo -i          # 只要能点能填的
webmuxd snapshot -t demo -s "#content"   # 只看这棵子树
webmuxd snapshot -t demo --viewport  # 只要视口内的
webmuxd snapshot -t demo --json      # 带 bbox / affords / enabled
```

```console
$ webmuxd snapshot -t demo -i
@e1   combobox  "" 
@e2   button    "百度一下"
@e3   link      "新闻"
$ webmuxd click -t demo @e1
$ webmuxd type  -t demo @e1 webmuxd
```

**`@e1` 是号,不是坐标也不是选择器。** 它指着那一个具体的 DOM 节点 ——
页面改版了、名字翻译了,号仍然对;而"第 3 个 `div.item`"不一定。

### 号只增不重用

第二次 `snapshot` 从 `@e13` 接着发,**不从 `@e1` 重来**:

```
snapshot  →  @e1 … @e12
click @e5 →  页面变了
snapshot  →  @e13 … @e20      ← 不是又一批 @e1
```

agent-browser 那边是重来的(它文档里明写着 `@e1` 第二次指着另一个元素)。
**我们不跟这一条** —— 重用把"拿着过期的号去点"从一个**报错**
变成了一次**点错东西**,而[点错浏览器比敲错终端贵](../../../webmuxd/locate.py)。

代价是号会一直涨。这个代价是对的:号是从输出里抄的,没人要去猜下一个是几。

### 三种失败分开说

| 说的话 | 意思 | 该干嘛 |
| --- | --- | --- |
| `@e9 不认识 —— 这个 session 还没 snapshot 过` | 一次都没发过号 | 先 `snapshot` |
| `@e9 不认识 —— 现在发到 @e20,重新 snapshot 一次` | 号抄错了,或是上上次的 | 重新 `snapshot` |
| `@e5(那时是 button「登录」)已经不在页面上了` | 号对,**节点没了** | 页面变了,重新 `snapshot` |
| `@e5(那时是 …)是上一个页面上的号` | 号对,但**页面整个换过了** | 重新 `snapshot` |
| `@e5 是 t_2 上的号,不是这个 tab 的` | 换 tab 了 | 在那个 tab 上用,或重新 snapshot |

**第四种是拿一个真 bug 换来的。**

原来只验第三种 —— "那个节点还在不在"(`DOM.getBoxModel` 拿不拿得到)。
不够:**Chromium 会把 backendNodeId 复用给新文档里的节点**,于是导航之后
拿旧号去点,`getBoxModel` 照样成功,**点中的是另一个东西,而且不报错** ——
正是这套号声称要防的那件事。

实测撞到过:百度首页上的 `@e13`,在搜索结果页上点成功了,
点中的是结果页那个搜索框。

所以号还绑着**那份文档的 `loaderId`**(CDP 里文档的正身,每加载一份换一个)。
页面一换,这个 session 上的旧号一律作废。

**两道防线各管一种,都要有:**

| 情形 | 挡它的是 |
| --- | --- |
| 同一份文档,那个节点没了(**百度的搜索就是这种** —— 地址变了但没换文档) | 「已经不在页面上了」 |
| 整份文档换了(跨站导航) | 「上一个页面上的号」 |

只有第一道的时候,第二种情形会漏过去 —— 那正是撞到的那个 bug。

> 这个洞是**测试变快之后才露出来的** —— 以前每个动作后面挂着 5 秒的
> `settle`,慢到撞不上。**慢本身会藏 bug。**

### 为什么它回来了

我们把这个口子砍过一次(那时叫 `observe`),理由是
"那是一套关于 agent 该怎么用浏览器的意见,该留在调用方那边"。

**那个理由站不住。** 那套意见此刻仍然在跑 —— 每次 `click "登录"` 都要先
`Accessibility.getFullAXTree`、按 `INTERACTIVE_ROLES` 筛一道、量 bbox
([`locate.snapshot`](../../../webmuxd/locate.py))。
**藏起来没有让这套意见变小,只是让它没法被人调。**

agent-browser 给了更好的答案:把旋钮交出去(`-i` `-s` `--viewport` `--max`),
库不替调用方定死筛到什么程度。这一版就是这么做的。

> **`-c`(压掉空结构)和 `-d`(限深)我们没有** —— 它们是树形输出的旋钮,
> 而我们出的是**一张平表**。要缩范围用 `-s`:
> **划范围不丢信息,截断丢。**

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
