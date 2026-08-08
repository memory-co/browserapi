# webmuxd v1 · 规格

设计稿在 [`works`](works/) —— 讲**为什么**。这三个目录讲**做成什么样**。

| 目录 | 是什么 | 谁用 |
| --- | --- | --- |
| [`api`](api/) | HTTP + WS 的线上格式 —— **唯一真相** | 任何语言的 client |
| [`cli`](cli/) | `webmuxd` 命令,照着 tmux 设计 | 人、shell 脚本 |
| [`sdk`](sdk/) | Python 包 `webmuxd` | 写 agent 的代码 |

**cli 和 sdk 都不做 api 没有的事。** 每条命令、每个方法都是一次 HTTP 调用,
名字、参数、错误码都跟着 api 走。api 加了字段,另外两边才有得加。

## 1. 文件对照

三个目录的文件名**尽量对齐**,同一行讲的大致是同一件事:

| 讲什么 | api | cli | sdk |
| --- | --- | --- | --- |
| 全局约定、错误、总表 | [README](api/README.md) | [README](cli/README.md) | [README](sdk/README.md) |
| **tab bar** —— 列表、切换、导航 | [tabs](api/tabs.md) | [tabs](cli/tabs.md) | [tabs](sdk/tabs.md) |
| **agent browser** —— 观测、动作、日志 | [agent](api/agent.md) | [agent](cli/agent.md) | [agent](sdk/agent.md) |
| **事件流** —— 实时推送 | [events](api/events.md) | [events](cli/events.md) | [events](sdk/events.md) |
| **server** —— session 管理、代理、鉴权 | [server](api/server.md) | [server](cli/server.md) | [server](sdk/server.md) |

每个 cli/sdk 文件的开头写着它对应哪个 api 文件,结尾有一张对照表。

**但不强求一一对应。** 对齐是为了好找,不是为了整齐:

- **api 有、cli/sdk 没有**的很正常 —— `GET /api/tabs/{id}/favicon` 是给 UI 画图标的,
  终端里没意义。这类缺口在对照表最后一行明写「没覆盖的」,并说清怎么绕
  (`--json` + `curl`,或换另一边)。
- **cli/sdk 有、api 没有**的只能是**客户端便利**,见 §3。凡是这种都标出来。
  真要新增行为,先加到 api。
- 分文件也只是尽量:cli 的会话命令和 server 命令都在
  [cli/server.md](cli/server.md),因为对用户是一件事。

## 2. 同一件事的三种写法

```bash
curl -X POST localhost:7900/api/act \
     -d '{"actions":[{"type":"click","text":"提交订单"}]}'     # api
```
```bash
webmuxd click -t work "提交订单"                                # cli
```
```python
b.click("提交订单")                                             # sdk
```

三条走的是同一个端点、同一套定位语义([api/agent.md §4](api/agent.md#4-定位))、
同一份错误码([api/README.md §4](api/README.md#4-错误))。
定位不到时,三边都会把**候选**给你,而不是随便挑一个。

## 3. 只有 client 才有的东西

api 没有、cli/sdk 各自加的,只有这些 —— 都在客户端做,不进服务端:

| | cli | sdk |
| --- | --- | --- |
| 目标解析 | `-t work:购物车` 按标题匹配 | `Server().get("work")` |
| 输出 | `-F '#{tab_url}'` 格式化、表格对齐 | `Observation` / `Tab` 对象 |
| 错误 | 退出码([cli/README §6](cli/README.md#6-退出码)) | 异常树([sdk/README §3](sdk/README.md#3-异常)) |
| 断线 | `watch` 自动续传 | `b.watch()` 自动续传 |

多出来的这几样都不改变语义:`work:购物车` 只是先 `GET /api/tabs` 再本地匹配,
`obs.as_prompt()` 只是把 `elements` 数组换个排版。
