# session · 一个 session 的一生

**一句话**:它是**唯一一个认识所有域的地方** —— 而这也正是它今天
639 行、34 个方法的原因。

## 1. 今天什么样

`sessions.py` 1211 行,里面其实是三样东西:

```
Session          639 行 / 34 个方法    ← 这个域
ProcessRuntime   211 行               ← browser 域
RemoteRuntime     52 行               ← browser 域
Server           132 行               ← server 域
```

后两样住在这儿是上一次摊平时被层表逼过去的
([browser §1](browser.md#1-今天散在哪)),不是设计。

`Session` 那 34 个方法自己也分得开:

| 一组 | 方法 | 其实属于 |
| --- | --- | --- |
| 起、停、接线 | `start` `close` `_on_attached` `_resume` `release` | 这个域 |
| 事件流 | `_emit` `subscribe` `_recent` | 这个域 |
| 流水 | `log` `note_human_activity` `human_active` | 这个域 |
| **前台是谁** | `_on_foreground` `_confirm_front` `_ask_front` `_prepare_tab` | **tab 域** |
| 动作 | `act` `resolve_tab` `bring_to_front` | **page 域** |
| tab 接线 | `executor_for` `cdp_session_for` `open_tab` `refresh_tab` `_wait_ready` | **tab / page** |
| 探针回调 | `_on_binding` | **channel 域**(光标)+ page(人在动) |

**一半的方法不属于这个域。**

## 2. 该长成什么样

```
session/
  README.md
  shape.py     SessionRow(`webmuxd ls` 的一行)
  life.py      建、起、停、放行那个 waitForDebugger
  events.py    事件流:`_emit` / `subscribe` / 那个环
  log.py       那条流水(`log.jsonl`)
  logfmt.py    渲染 —— **CLI 和下载共用这一份**
  http.py      /api/events · /api/log*
  sdk.py  cli.py
```

搬走的:前台那四个方法 → `tab/front.py`;`act` 那组 → `page/`;
`executor_for` 这类接线留在 `life.py`(它就是"把各域接起来"这件事本身)。

## 3. 它是唯一允许认识所有域的地方

这条要写死,否则"编排"会变成"什么都往里塞":

> **`session/` 可以 import 任何域;任何域都不许 import `session/`。**

今天有两处反着来:`screen.py` 和 `browser_ui.py` 都 `import sessions`
—— 而它们分别属于 channel 和 native。这两条在层表里今天是**合法的**
(同层可以互相认识),按域分之后它们会红,**而红是对的**。

## 4. 那条流水的规矩

九类,前八类回答"谁做了什么",`diag` 回答"出了什么问题"。
它们**同一条流、同一套 `seq`**,所以排查时只看一个地方就够。

这条是拿事故换来的:

> 以前诊断只进 `server.log` —— 那是**整台 server 一份**,十个 session 混在
> 一起,而且每条都不带 session id。最难受的是:CPU 打满那种时候,
> 操作日志是**完全空白**的(没有人在"做"任何事),而真相在另一份文件里。

`logfmt.py` 和 `log.py` 分开也是拿事故换的:两处各写一遍渲染,
改了一处另一处没改,**人拿到的两份"同一个 session 的日志"长得不一样**。

## 5. ↔ 别处

| | |
| --- | --- |
| 一个 server 一个口,session 是 `/s/<id>/` | [k](../works/k-one-server.md) |
| 那条流水 | [api/log](../../v1/api/log.md) · [`tests/the_scrollback/`](../../../tests/the_scrollback/) |
