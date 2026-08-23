# moving · 怎么走过去,以及它会疼在哪

**一句话**:这是一次**比上次摊平更大**的搬家,所以第一步不是搬,
是先让"没搬完"这件事变红。

## 1. 它会疼在哪 —— 三条,说在前面

### 1.1 目录回来了,而上一次是刚拆掉的

[j §3](../works/j-layout.md) 写着"**没有子包 —— 子包是用来藏东西的**",
[j §7](../works/j-layout.md) 写着摊平之后暴露出的真问题是反向依赖,
"**子目录一直在替这些遮丑**"。

答案在 [README §2.1](README.md#21-先回答上一次为什么要摊平):
那句话是对**按角色分的目录**说的。判据换一条更硬的:

> **打开一个目录,能不能回答"改这件事要动哪儿"。**

`core/` 回答不了,所以它在藏东西;`tab/` 回答得了。
**这条判据要写进 j-layout,替换掉"不许有子包"那句** ——
否则下一个人会拿旧那句来推翻这次。

### 1.2 文件会更多

今天 26 个。按 §3 那张表,大约 **9 个目录 / 55 个文件**。

多出来的主要是每域一个 `shape.py` 和一个 `http.py`。
**这是明码标价的**:换到的是"一个概念一处、一件事一处",
以及那五条能被断言的规矩。

如果嫌多,可以合的是 `sdk.py` / `cli.py` 那两层 —— 但**不建议先合**:
它们正是今天让一次改动动六个文件的那两片。

### 1.3 `git blame` 会断一次

上次摊平也断过。缓解只有一条:**第 1 步只动位置,不动内容**,
让 `git log --follow` 还追得到。

## 2. 顺序

**先立规矩,再搬。** 反过来的话,搬到一半没有任何东西告诉你哪儿还没搬完。

| | 做什么 | 做完什么样 |
| --- | --- | --- |
| 1 | 加 §4 那五条断言,以及一张空的域表 | **全红**。红的就是待办清单 |
| 2 | 建目录,**只动位置**:`tabs.py` → `tab/table.py` 这种一对一的先搬 | 少几条红 |
| 3 | 把 `models.py` 按域拆进各家 `shape.py` | `models.py` 消失 |
| 4 | 把 `sessions.py` 那三块分家:`Session` 留下,两个 Runtime → `browser/`,`Server` → `server/` | 1211 行那个没了 |
| 5 | 把 `serve.py` 那 60 个 handler 按域分进 `*/http.py`,`server/app.py` 只留装配 | |
| 6 | 把 `api.py` / `cli.py` 按域分进 `*/sdk.py` `*/cli.py` | |
| 7 | 收拾剩下的:`RefTable` → `page/refs.py`、`SessionInfo.detail` 那个袋子写成字段 | 全绿 |

每一步跑全量。**第 1 步之后一直是红的,这是对的** —— 那几条红说的就是"还没搬完"。

> 上一次摊平的经验:"真正花时间的不是搬,是搬完暴露出来的反向依赖"。
> 这次已经知道两处:`screen.py` 和 `browser_ui.py` 都 `import sessions`
> ([session §3](session.md#3-它是唯一允许认识所有域的地方))。
> **它们今天在层表里是合法的**(同层),按域分之后会红。

## 3. 目标形状

```
webmuxd/
  exceptions.py          底座:谁都能用,不属于任何域

  browser/    shape cdp process remote pick
  install/    shape probe fetch record
  tab/        shape table front http sdk cli
  page/       shape find refs act see http sdk cli
  native/     shape dialogs downloads files perms auth http sdk cli
  channel/    shape words cast jpg vnc dom frame input sidecar http cli
  session/    shape life events log logfmt http sdk cli
  server/     app auth index registry run
  face/       transport mirror entry parser

  _client/    观看页的构建产物(不进 git)
  _sidecar/   注进页面里那段的构建产物(不进 git)
```

## 4. 怎么守住

五条,都放 [`the_layout_holds/`](../../../tests/the_layout_holds/)(不跑浏览器,永远会跑):

| | 断言 | 挡的是 |
| --- | --- | --- |
| 1 | **域之间只许往下 import**(域表在测试里,加目录就要想清楚它在第几级) | 反向依赖,和上次摊平暴露的是同一类 |
| 2 | **`face` / `*/sdk.py` / `*/cli.py` 只许 import `*/shape.py`** | SDK 拖进实现;比今天那条"不许 import serve"挡得更靠前 |
| 3 | **`*/shape.py` 一行 import 都没有**(连 `exceptions` 都不许) | `RefTable` 那类漂移 —— 它想留在 shape 里就会红 |
| 4 | **只有 `*/http.py` 认识 aiohttp** | HTTP 那一层渗进域里 |
| 5 | **每个域一句话**(`*/README.md` 第一行) | 想不清楚它是什么事,就是还没设计完 |

今天已经有的那几条(三条腿互不认识、models 只认识 exceptions、
给人用的两个不认识 serve、一件事一个词)**要么留着,要么被上面某条覆盖**,
一条都不能悄悄丢。

### 4.1 第 3 条是这次真正的修复

`RefTable` 不是有人决定把服务塞进模型层,是它**一点一点长到 67 行的**:

> 加一个字段 → 加一个方法 → 那个方法要报错 → import 一下 `exceptions` →
> 四种失败分开说 → 67 行。

**每一步单独看都合理,而且中间没有任何一步会红。**

规矩 3 让那条路上的第四步当场变红。
拆本身不产生价值 —— **能被守住才产生价值。**

## 5. 什么时候值得做

判据用这个项目自己那句:**tmux 会做这个吗?**

会 —— 但不是为了好看。做它的理由只有一条,而且是量出来的:

> 扁平化之后 26 个提交,**平均一次改动动 6.2 个文件**;
> 0.18.0 那次改"前台是谁"这**一个概念**,动了五个文件。

如果接下来一段时间主要是加功能(而不是改结构),那这个数字会一直在那儿收税。
反过来,如果近期不打算大改,**这件事可以先只做第 1 步** ——
把五条断言立起来,让它红着。红着不影响发版,但它会让每一次新的漂移当场被看见。
