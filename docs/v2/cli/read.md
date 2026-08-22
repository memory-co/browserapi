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

## 2. `get` 和 `is` —— 问一个,别抓一整页

```bash
webmuxd get value -t demo @e13          # 框里现在是什么
webmuxd get text  -t demo "登录"         # 那个东西上的字
webmuxd get attr  -t demo "新闻" href    # 一个属性
webmuxd get count -t demo --css h3      # 有几个
webmuxd get box   -t demo @e13          # [x, y, w, h]
webmuxd get url   -t demo               # 这两样不落到元素上
webmuxd get title -t demo

webmuxd is visible -t demo @e13 && echo 看得见
webmuxd is enabled -t demo @e13
webmuxd is checked -t demo "同意条款"
```

**`is` 的答案在退出码里**(`0` 是,`1` 否),和 `has` 一样 ——
给脚本用的是码不是字。stdout 上也会打 `true` / `false` 给人看。

### 为什么非有不可

在它们之前,"确认一个值"只有一条路:**把整页再 `snapshot` 一遍**。

而 `snapshot` 会给页面上每个元素**发一个新号**,于是:

```
缺 get  →  每次确认都抓整页  →  号在膨胀  →  旧号语义说不清
```

实测过:同一个节点在一次会话里被发了 `e13 / e38 / e64 / e90 / e116`
五个号,五个都还能用。整条流的转录在
[issue](../issues/每次确认都要抓一整页-于是号在膨胀.md)。

补上 `get` 之后,[`v2_cli_simple`](../../../tests/v2_cli_simple/) 那条流里
`snapshot` 从**三次降到一次**,整条流发出去的号从 114 个降到 25 个。

### 读不 settle

`get` / `is` / `count` **跳过那个"等页面稳下来"**
([`act.READ_ACTIONS`](../../../webmuxd/act.py))。

`settle` 的意思是"做完之后等页面稳下来",而读没有"做完" ——
它什么都没改。补完 `get` 之后第一次量,它比 `snapshot` 慢六倍
(2430ms vs 417ms),差的全是这个。

```
get value    2430ms → 340ms
click        2490ms → 2490ms      ← 它真的改了页面,该等
```

**同一件事两个价钱,那是路走错了,不是它本来就贵。**

### 和 agent-browser 的对照

| agent-browser | 我们 | |
| --- | --- | --- |
| `get text\|html\|value\|attr\|count\|box <sel>` | 一样 | ✅ |
| `get url` / `get title` | 一样 | ✅ |
| `is visible\|enabled\|checked <sel>` | 一样,**外加退出码** | ✅ |
| `get styles <sel>` | 🔲 没有 | 要它得先想清楚"哪些属性" |
| `get cdp-url` | 🔲 没有 | 我们的 CDP 端点不对外 |

**`<sel>` 在我们这儿是[整套定位](act.md#1-定位五种写法一条梯子)**,
不只是 CSS:`@e13` / 可见文字 / `--role --name` / `--css` 都行。

## 3. `capture` 的两个形状

```console
$ webmuxd capture -t demo | head -3        # 正文,对应 capture-pane -p
$ webmuxd capture -t demo --shot p.webp    # 那一刻的页面
✓ 存到 p.webp
```

**WebP 不是 PNG** —— 同样画质小一半,而这条流量要走网络。

🔲 **待讨论:`--full`(整页)。** 后端有(`full_page=true`),CLI 没给。
`pdf` 后端也没有。
