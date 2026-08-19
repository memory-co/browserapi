# 13 · 给 agent 的操作面,和一条行为流

**一句话**:agent 能做的事是一张**动词表**,人和 agent 做过的事是**同一条流**,
每条带着"谁干的"。这两件事是一件事的两面 —— 操作面定义了能发生什么,
行为流记录了发生了什么。

> 这一篇有一半是横向调研(§1),看了 BrowserLess / Steel / Browserbase /
> Kernel / Hyperbrowser / Anchor / Cloudflare Browser Run 七家。
> **调研的目的不是抄形状,是找出他们各自被什么约束住了** ——
> 我们的约束和他们不一样,所以有些他们做不到的事我们白拿,
> 有些他们轻松做到的事我们反而要额外做。

## 0. 先说清楚我们已经有什么

**这一节是实况,不是设计。** 下面每一条都在跑。

### 0.1 动词表:17 个,加上 tab 那一组

[`core/act.py`](../../../webmuxd/core/act.py) 的 `_dispatch` 分派这些:

| 组 | 动词 |
| --- | --- |
| 导航 | `goto` `back` `forward` `reload` `stop` |
| 指点 | `click` `hover` `scroll` |
| 输入 | `type` `clear` `key` `select` `check` `upload` |
| 读 | `extract` `wait_for` |
| 逃生舱 | `js` |

**`open` 不在这张表里** —— 开 tab 是 `POST /api/tabs`,因为它改的是 session 的
tab 表而不是某个页面([05](05-active-tab.md))。这个切分是对的,但**没有在任何
一篇里说清楚**,所以外面的人第一反应总是去 `act` 里找 `open`。§2.1 补这一刀。

### 0.2 一条流,人和 agent 都在里面

日志是 tmux 的 scrollback,一个 `log.jsonl`,`seq` 和事件流共用一个计数器
([v1/works/03](../../v1/works/03-log.md))。**关键是它记了 `user`**:

```jsonc
{"seq": 41, "kind": "action", "user": "api",   "action": "click", "target": {"label": "登录"}, "ok": true, "ms": 210}
{"seq": 42, "kind": "action", "user": "human", "action": "pointerdown", "target": {"point": [80, 12]}, "hit": {"role": "input", "name": "密码"}}
```

人干的怎么进来的:页面里注入一个捕获阶段的监听器
([`core/shim.py`](../../../webmuxd/core/shim.py)),`pointerdown` / `keydown`
报回来 —— **页面 `stopPropagation` 也拦不住**。

### 0.3 人一碰,agent 自动让路

[`serve/session.py`](../../../webmuxd/serve/session.py) 里那个 `human_active`:
人一有输入就开一个让路窗口,窗口内 `POST /api/act` 直接返回

```jsonc
{"error": {"code": "busy_human", "message": "人正在操作",
           "details": {"retry_after_ms": 2400}}}
```

**这个形状和七家都不一样,§1.3 会看到。**

## 1. 七家在做什么

> 下面的 API 名来自各家公开文档(2026-08 查)。有些结论来自搜索摘要而不是
> 一手文档,标了「据其文档」的是我实际读到原文的,其余按说法转述 ——
> **这一节是拿来对照思路的,不是拿来当规格抄的。**

### 1.1 操作面:三种形状

| 形状 | 谁 | 长什么样 |
| --- | --- | --- |
| **CDP / Playwright 直通** | Browserless、Browserbase、Kernel、Hyperbrowser、Steel、Cloudflare | 给你一个 `wss://` 端点,你拿 Playwright/Puppeteer 连上去。**他们不定义动词,浏览器定义** |
| **REST 单动作** | Browserless(`/screenshot` `/pdf` `/content` `/scrape`)、Steel(`/scrape` `/screenshot` `/pdf`) | 一个请求 = 起一个浏览器 + 干一件事 + 关掉。**无状态** |
| **语义动作** | Stagehand(`act` / `extract` / `observe` / `agent`)、Steel CLI(`open` `snapshot` `fill` `click` `wait`)、Anchor 的 AI task | 用自然语言或语义定位,模型在中间 |

**值得注意的是第三种和我们的重合度。** Stagehand 的
`act()` / `observe()` / `extract()` 和我们的 `act()` / `observe()` / `extract`
几乎同名同义,而两边是独立长出来的 —— 这说明"给 agent 的浏览器操作面"
正在收敛到这三个原语上:**做一下、看看有什么、把东西取出来**。

差别在于**语义解析放在哪**:Stagehand 把 LLM 放进 SDK 里(`act("点登录")`
会调模型去找元素),我们不放 —— [定位是分档匹配,有歧义就给候选不替你挑](../../v1/works/README.md)。
这条差别不是优劣,是**谁来承担猜错的后果**:他们替你猜,我们把候选交回给你的模型。

### 1.2 live view:谁的只读是真的

| | 怎么给 | 只读怎么做 |
| --- | --- | --- |
| **Browserbase** | `sessions.debug(id)` → `debuggerUrl` / `debuggerFullscreenUrl` | iframe 上加 `pointer-events: none` |
| **Hyperbrowser** | 建 session 时就返回 `liveUrl`,token 12 小时过期 | `viewOnlyLiveView: true` |
| **Cloudflare** | `Cloudflare.getLiveView` → `devtoolsFrontendUrl` | — |
| **Kernel** | 每个 session 一个 live view,可嵌 iframe | — |
| **我们** | 和 API 同一个口(`/`),token 签在 URL 里 | **服务端丢弃输入**([04 §3](b-input.md)) |

**`pointer-events: none` 是前端的事。** 拿到那个 URL 的人打开 DevTools 删掉
那行 CSS,就能操作了 —— 它挡的是"不小心碰到",不是"不让他碰"。
我们那条是服务端在 WS 上按连接的权限丢弃,前端连按钮变灰都不做
(那是[03 §1](b-input.md) 那个收口的直接好处:**所有输入都必须经过我们翻译**)。

> 这不是说他们做错了 —— 他们给的是 CDP 直通,**输入本来就不经过他们**,
> 想在服务端丢弃就得去解析 CDP 流量。约束不同,结论不同。

### 1.3 人机交接:四种形状,我们是第五种

| | 怎么交接 |
| --- | --- |
| **Cloudflare** | `Cloudflare.handoff`(带指示和超时,最长 30 分钟)→ 人操作 → `Cloudflare.handoffComplete` 事件带成功/失败。**把交接做成了 CDP 命名空间的扩展** |
| **Anchor** | 任务上开 `human_intervention: true` → agent 挂起 → `GET /v1/sessions/{id}/agent/…` 拿待处理请求 → `POST …/respond-to-human-intervention` → 触发 `intervention.resolved` webhook |
| **Browserbase / Hyperbrowser** | 给一个 live view URL,**没有协调机制** —— 人和 agent 可以同时动 |
| **Kernel** | 托管登录面板:agent 把一个交互面板交给人去完成登录/二次验证 |
| **我们** | **人不用申请,agent 也不用交出去** —— 人一碰画面就开让路窗口,agent 的下一个 `act` 拿到 `busy_human` + `retry_after_ms`(§0.3) |

前四种都是**显式交接**:得有人先说"我要交出去"。这有个前提 ——
**平台看不见人什么时候动手**,所以必须由 agent 声明。

我们看得见,因为[人的输入也走我们的通道](b-input.md)。于是可以做成**隐式**的:

> **人不需要"申请接管",他碰一下就是接管。**

代价也要说清楚:让路窗口是**时间**驱动的(默认几秒无输入就自动交还),
agent 不知道人"做完了没有",只知道"人这会儿没在动"。
Cloudflare 那个 `handoffComplete` 带成功/失败,我们没有对应的东西 —— §3.3。

### 1.4 行为流 / 回放:各家记什么

| | 记什么 | 标不标"谁干的" |
| --- | --- | --- |
| **Steel** | Agent Logs:click / navigation / scroll / keyboard,带 timestamp 和 target element,时间线点一下跳到回放对应时刻 | 只有 agent 的 |
| **Kernel** | 浏览器 telemetry:console、network、页面生命周期、**user interactions**、验证码求解、崩溃等运行信号;**按类别 opt-in**,可实时流也可事后拉 | 分类里有 user interactions,但没看到"人 vs agent"的区分 |
| **Browserbase** | rrweb 录制(DOM 级重放) | rrweb 记的是 DOM 变化,不记意图 |
| **Anchor** | session recording 开关 | — |
| **我们** | 三类 + 四类原生 UI 的 scrollback,一行 JSON | **每条带 `user`** |

**这一栏是我们唯一明显领先的地方,而且是白拿的。**
因为人的输入和 agent 的动作**都必须经过 CDP `Input.*` 这个收口**,
两边天然在同一条链路上。给 CDP 直通的平台做不到这件事:
人在 live view 里点的那一下,对他们来说和 agent 发的 `Input.dispatchMouseEvent`
在线上**是同一种字节**。

> 反过来说,我们缺的是他们有的:**没有回放**。Steel 的"点时间线跳到那一刻"、
> Browserbase 的 rrweb、Kernel 的 MP4 章节标记 —— 我们只有文字流和
> 单帧截图([v1/works/03](../../v1/works/03-log.md))。§4.3。

### 1.5 一条容易看漏的:他们都在卖"起得快"和"不被封"

七家里有六家把**冷启动时间**(Kernel 说 sub-150ms)、**stealth / 反检测**、
**住宅代理**、**验证码求解**放在首页。这是云服务的竞争维度,
**不是我们的** —— webmuxd 是一个你自己跑的库(`tmux` 不卖机房)。

但有一条值得抄:**持久化 profile**。他们叫 persistent profiles / contexts,
用来跨 session 保住登录态。我们现在是 `--data-dir` 一个目录,
[07](07-runtime.md) 提过但没有产品面。§3.4。

## 2. 操作面该长什么样

### 2.1 `open` 为什么不在动词表里

三个层次,**改的东西不一样**:

| | 例子 | 改的是 | 走哪儿 |
| --- | --- | --- | --- |
| **session 级** | 起一个、停一个、只读分享 | 进程和端口 | CLI / `Webmuxd.session()` |
| **tab 级** | `open` `close` `activate` `reorder` | session 的 tab 表 | `/api/tabs` |
| **页面级** | `click` `type` `goto` … | 那一个页面里的状态 | `/api/act` |

`open` 在中间那层。把它塞进 `act` 会立刻出问题:`act` 是**按 tab 串行**的
(一个 tab 一个 executor,遇错即停),而"开一个新 tab"的结果是**另一个 tab**
—— 串行语义对不上。

**但这件事得写在产品面上。** 现在只有读完 `05` 和 `api/tabs.md` 才知道,
而 agent 的第一个动作几乎一定是"打开一个网页"。

### 2.2 一个动词表该有的三条性质

**① 动词是封闭集合,`js` 是唯一的逃生舱。**
封闭才能被日志、被回放、被权限收口。`js` 那条要**在日志里显眼**,
因为它绕过了上面所有的语义。

**② 定位失败不是异常,是候选。** [`act()` 不抛](../../v1/works/README.md) ——
写 agent 循环时要把候选喂回模型自我纠正,而不是被异常打断。这一条 Stagehand
用另一种方式解决(SDK 里的模型直接重试),**我们把决定权留在外面**。

**③ 每个动词都要能回答"做完之后页面变成什么样"。**
这是 `settle` + `after` 那一套([v1/works](../../v1/works/README.md))。
七家里只有 Stagehand 的 `observe` 有类似的东西,其余都是"你自己再截个图看看"。

### 2.3 还缺的动词

对着 agent 实际会撞上的东西看,**这几个现在只能用 `js` 硬写**:

| 缺的 | 为什么值得单列 | 现在只能 |
| --- | --- | --- |
| `drag` | 拖拽排序、滑块验证 | `js` 合成事件,而合成的常被判定为非人 |
| `switch_frame` | 跨 iframe 的页面越来越多 | `js` 里钻 |
| `download` 触发 + 等待 | 下载有专门的事件和端点([06](06-no-desktop.md)),但没有"点了它然后等下载完"这个动作 | 点完自己轮询 `/api/downloads` |
| `wait_for_navigation` | `wait_for` 现在等的是元素 | `settle` 兜一部分 |

**不是全都要做。** 判据还是那句:tmux 会做这个吗 —— 换到这儿是
**"不做的话,agent 是不是只能掉进 `js` 逃生舱"**。掉进去就意味着那一段
不再被日志和权限看见,那才是真正的代价。

## 3. 行为流该长什么样

### 3.1 一条流,每条带 actor —— 这条已经成立,要把它抬成契约

现在 `user` 字段是实现细节(v1 就有,当时用来标"哪个团队成员干的")。
**它应该被抬成一条明写的契约**:

> **任何改变了远端状态的动作,都会在同一条流里留下一条,并且标明是谁干的。**

这句话的分量在于它划了一条边界:什么算"动作"、什么不算。
现在的规矩是 [`core/log.py`](../../../webmuxd/core/log.py) 那句:
**页面自己的变化(标题变了、loading 变了)不进日志** —— 没有人"做"它们。
这条要留着,而且要写进产品面,否则日志会退化成事件流。

### 3.2 三个真实的缺口

**① 人打的字,现在一条都没有。**

实测:人在画面里点一下 → 有 `pointerdown` 一条;人接着打一串中文 → **零条**。
因为中文走 `Input.insertText`([03 §3](b-input.md)),它**不产生页面 keydown**,
而探针是挂在 `keydown` 上的。于是"人在这个表单里填了东西"这件事,
在行为流里是**不存在**的。

修的方向不是去补探针,而是**换一个记录点**:人的输入本来就经过
[`view/input.py`](../../../webmuxd/view/input.py) 那一层翻译 ——
在那儿记,是"由构造保证"的,不是靠页面回报。

**② "是人还是我们"靠 0.4 秒的时间窗判。**

[`serve/session.py`](../../../webmuxd/serve/session.py) 里 `_SELF_WINDOW = 0.4`:
我们自己派发动作之后 0.4 秒内,页面报上来的输入都算我们的。
**人在这 0.4 秒里点了一下,那一下就消失了** —— 不进日志,也不开让路窗口。

同样地,记录点换到我们自己的输入层之后这个问题就不存在了:
那条连接上来的一定是人,不需要推断。

**③ 记的是控件的身份还是内容?**

写这一篇时实测出一个漏:探针原来报 `innerText || value`,
而 `value` 在密码框上**就是明文密码** —— 它会进 `log.jsonl`,
`webmuxd log` 打得出来、`log/bundle` 打包带得走。
`log.py` 的注释写着"明文不该走到这儿",但那条掩码只管 API 那条路。

已经修了:**控件的身份是它的标签,不是它的内容**
(`aria-label` → `<label>` → `placeholder` → `name`/`id`,表单控件一律不取 `value`)。
`tests/pixels_on_a_wire` 有两条守着,其中一条不依赖跑浏览器所以永远会跑。

> 这条值得单独记一笔:**行为流天然是个数据外泄面**。
> 它记得越细越有用,也越容易把不该记的记进去。
> 判据可以定成一句话:**记"他动了哪个控件",不记"控件里是什么"** ——
> 后者要看,有 `observe` 和截图,那两条路上有明确的授权。

### 3.3 交接:隐式够用,但缺一个"人说完了"

§1.3 说了我们的让路是隐式的,比"agent 必须先申请"好。
但 Cloudflare 那个 `handoffComplete` 解决的是另一个问题:
**人做完了没有?**

我们现在只能靠"人几秒没动了"来猜。对"帮我过一下二次验证"这种场景,
猜是够的(人做完就不动了);对"你看着办,我先去开个会"就不够。

不急着做,但要记着:如果做,形状应该是**人这边一个按钮 + 一条事件**,
而不是 agent 那边一条阻塞调用 —— 因为在我们这儿,**人随时可以介入,
不需要 agent 允许**,那么"结束"也该由人说。

### 3.4 持久化 profile:七家都有产品面,我们只有一个目录

现在 `--data-dir` 指哪儿,登录态就在哪儿。够用,但两件事没有:

- **没有"这个 profile 里有哪些站点登录着"** —— 人和 agent 都看不到
- **没有跨机器搬运** —— 他们叫 profiles / contexts,可以导出再挂到另一个 session

这两条都不是画面这条主线上的,列在这儿是因为 §1.5 让它显形了。

## 4. 该借鉴什么

| 借鉴 | 来自 | 为什么 |
| --- | --- | --- |
| **把交接做成协议里的一等公民** | Cloudflare 的 `Cloudflare.handoff` / `handoffComplete` | 不是加一个 REST 端点,而是**在 agent 已经在用的那个协议里**加一对命令和事件 —— 这样它天然被日志和权限覆盖 |
| **事件按类别 opt-in** | Kernel 的 telemetry | 我们现在是"三类日志全记"。console 和 network 那两类量级差一个数量级,**默认全开会把 scrollback 冲掉** |
| **时间线和回放对齐** | Steel 的 Agent Logs | 我们的 `seq` 已经是日志和事件流共用的了,**离"点一条跳到那一刻"只差一个画面归档** |
| **只读要在服务端** | 反面教材:`pointer-events: none` | 已经做了,值得写下来 |

**不借鉴的**:

- ❌ **SDK 里塞模型**(Stagehand 的 `act("点登录")` 内部调 LLM)。
  我们的定位是分档匹配 + 给候选 —— 猜错的后果留在外面。
- ❌ **stealth / 住宅代理 / 验证码求解**。那是云服务的竞争维度,不是库的。
  tmux 不卖机房。
- ❌ **无状态的 REST 单动作**(`/scrape` `/screenshot` 起一个浏览器干一件事就关)。
  webmuxd 的整个立身之本是**那个浏览器活得比连接久** —— 无状态端点是反的。

## 5. 还没定的

| | |
| --- | --- |
| §3.2 那三条改动的落地顺序 | ①(人打的字)是缺口,②(时间窗)是同一处改动的副产品,③ 已经修了 |
| 动词表要不要补 §2.3 那四个 | 判据是"不做的话是不是只能掉进 `js`" |
| 事件分类 opt-in 怎么和现在的三类共存 | Kernel 那套是另一个维度,硬塞会把 `KINDS` 撑爆 |
| 回放要不要做 | 要的话是"给每条动作存一帧"还是"存 rrweb 流"——后者和我们"画面是像素"的路线正交,得单独论证 |
| profile 的产品面(§3.4) | 和画面无关,但七家都有,说明是真需求 |

## 6. ↔ 别处

| | |
| --- | --- |
| 输入为什么是收口 —— 这一篇一半的前提 | [03 §1](b-input.md) |
| 只读为什么在服务端 | [04 §3](b-input.md) |
| tab 表和 `open` 在哪一层 | [05](05-active-tab.md) |
| 六类原生 UI —— 它们也是行为流的一部分 | [06](06-no-desktop.md) |
| 日志是 scrollback 不是归档 | [v1/works/03](../../v1/works/03-log.md) |
