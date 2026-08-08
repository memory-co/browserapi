# webmuxd v1 · 规格

设计稿在 [`works`](works/) —— 讲**为什么**。这三个目录讲**做成什么样**。

| 目录 | 是什么 | 谁用 |
| --- | --- | --- |
| [`sdk`](sdk/) | Python 包 `webmuxd` —— **主体**,行为定义在这儿 | 写 agent 的代码 |
| [`api`](api/) | HTTP + WS 的线上格式 —— sdk 的**导出面** | 调试、非 Python 的 client |
| [`cli`](cli/) | `webmuxd` 命令,照着 tmux 设计 | 人、shell 脚本 |

**顺序是 sdk → api,不是反过来。** 定位规则、元素筛选、`candidates`、日志格式,
这些行为都定义在 lib 里;HTTP 那层是把它导出去的壳,为**调试**和**非 Python 集成**而加。
为什么这么定,见 [works/02](works/02-lib-and-api.md)。

所以:**api 不做 sdk 没有的事**。反过来可以 —— lib 有些东西
(`with` 自动清理、按标题找 tab、`obs[12]` 下标)是纯客户端的,不必导出。
CLI 是 lib 的一个用户,和你的代码平级。

## 1. 文件对照

三个目录的文件名**尽量对齐**,同一行讲的大致是同一件事:

| 讲什么 | sdk(主体) | api(导出面) | cli |
| --- | --- | --- | --- |
| 全局约定、错误、总表 | [README](sdk/README.md) | [README](api/README.md) | [README](cli/README.md) |
| **tab** —— 句柄、列表、切换、导航 | [tab/](sdk/tab/) | [tabs](api/tabs.md) | [tabs](cli/tabs.md) |
| **页面上做和看** —— 动作、定位、观测 | [tab/input](sdk/tab/input.md) · [tab/read](sdk/tab/read.md) | [act](api/act.md) | [act](cli/act.md) |
| **操作日志** | [log](sdk/log.md) | [log](api/log.md) | [log](cli/log.md) |
| **事件流** —— 同步机制,只有画 UI 的才碰 | [events](sdk/events.md) | [events](api/events.md) | [events](cli/events.md) |
| **session** —— 起停、runtime、代理、鉴权 | [session](sdk/session.md) | [server](api/server.md) | [server](cli/server.md) |

每个文件的开头写着它对应哪几个,结尾有一张对照表。

**但不强求一一对应。** 对齐是为了好找,不是为了整齐:

- **sdk 有、api 没有**的很正常 —— tab 句柄、内存里那份 tab 表、`with` 自动清理、
  `obs[12]` 下标,这些是客户端的东西,导出去没意义。见 §3。
- **api 有、sdk 没有**的只有一处,而且是故意的:session 的遍历和清理
  (`GET /api/sessions`、`GET /api/server`)。lib 里没有 `Server` 类 ——
  那是运维,归 CLI 的 `ls` / `kill`([sdk/session.md §5](sdk/session.md#5-lib-不管有哪些-session))。
- **api 有、cli 没有**的也很正常 —— `GET /api/tabs/{id}/favicon` 是给 UI 画图标的,
  终端里用不上。这类缺口在对照表最后一行明写「没覆盖的」,并说清怎么绕。
- 分文件也只是尽量:cli 的会话命令和 server 命令都在
  [cli/server.md](cli/server.md),因为对用户是一件事。

## 2. 同一件事的三种写法

```python
tab.click("提交订单", user="claudecode")                        # sdk —— 主体
```
```bash
webmuxd click -t work "提交订单" --user claudecode              # cli
```
```bash
curl -X POST localhost:7900/api/act \
  -d '{"actions":[{"type":"click","text":"提交订单"}],"user":"claudecode"}'   # api
```

三条落到的是**同一个定位引擎**([sdk/tab/read.md §2](sdk/tab/input.md#1-定位五种写法)):
精确匹配优先 → 子串 → 大小写不敏感 → 仍然多于一个就报错并列出全部候选,绝不随便挑一个。
定位不到时三边都把**候选**给你,只是形态不同 —— 异常属性、终端里几行字、JSON 的 `details`。

## 3. 表达力的落差

同一个东西在三边**必然长得不一样**,因为 JSON 里没有对象、没有异常、没有惰性:

| | sdk | api | cli |
| --- | --- | --- | --- |
| 拿一个 tab | `tab = web.open(url)` 句柄 | `201` + 一个 `{id}`,之后自己拼路径 | `new-tab` 打印一行 |
| 读 `url` / `title` | **内存,0 往返** | 每次一个 `GET` | 每次一个 `GET` |
| 定位失败 | `except NotFound as e: e.candidates` | `404` + `details.candidates` | 退出码 4 + 列候选 |
| 观测 | `obs[12]`、`obs.as_prompt()` | 一坨 JSON 数组 | 几行紧凑文本 |
| 图标 | `tab.favicon` → bytes,惰性取 | 一个 URL 字符串 | 没有 |
| 断线 | `web.watch()` 自己重连并补全量 | 你自己带 `?after=` | `watch` 自己重连 |

**这个落差就是为什么主体在 lib。** 让表达力最弱的那层当起点,
另外两层只能跟着退化成 dict 搬运 —— [works/02 §1](works/02-lib-and-api.md#1-为什么是-lib-而不是-api)。

落差不改变语义:`obs.as_prompt()` 只是把 `elements` 换个排版,
`work:购物车` 只是先拉一次 tab 列表再本地匹配。
