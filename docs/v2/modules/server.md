# server · 一个口,和两个面

**一句话**:`server` 是**一个口**;`face` 是**谁在问** —— 两件事,
今天挤在 `serve.py` / `api.py` / `cli.py` 三个大文件里。

## 1. 今天什么样

```
serve.py    899 行,60 个 handler 平铺在一个文件里
api.py     1016 行  Tab(310) + Session(159) + Webmuxd(100) + Mirror(196) + Transport(79)
cli.py     1046 行  45 个 cmd_* + 一个 200 行的 _parser
sessions.py 里 Server  132 行
```

`serve.py` 那 60 个 handler **已经按域分好组了**,只是没分文件:

```
h_tabs h_tab_one h_tab_new h_tab_close h_tab_activate h_reorder h_history   → tab
h_act h_snapshot h_screenshot h_text                                        → page
h_pending h_downloads h_download_file h_upload h_files h_perms h_auth_*     → native
h_view h_xpra h_rrweb h_res h_mode_get h_mode_set h_viewport                → channel
h_log h_log_txt h_bundle h_events                                           → session
h_index h_sessions h_session_new h_server h_static                          → server
```

## 2. 该长成什么样

**handler 跟着域走**,`server/` 只留下真正属于"一个口"的东西:

```
server/
  README.md
  app.py       路由装配 —— 把各域的 http.py 挂上去
  auth.py      token:读写分离、只读的静默丢弃
  index.py     那张 session 列表 + 内置观看页的静态文件
  registry.py  哪些 session 活着(今天 `sessions.Server`)
  run.py       起停这个进程
```

**`app.py` 是唯一一处能看见全部路由的地方** —— 这一点要保住:
今天 `build()` 那 83 行是这个项目最有用的一张地图。

## 3. 两个面

`api.py` 和 `cli.py` 也按域切,但**它们是横切的**:

```
tab/sdk.py       tab/cli.py
page/sdk.py      page/cli.py
channel/…        …
face/
  transport.py   那条 HTTP 连接 + 重试 + 错误还原
  mirror.py      订事件流、维护内存副本(`sess.tabs` 读内存不发请求)
  entry.py       `Webmuxd()` / `Session` 两个门面
  parser.py      argparse 那 200 行
```

### 3.1 面只认形状,不认实现

这是 `models.py` 今天买到的那条保证,**按域分之后要用规矩接住**:

> **`face` 和 `*/sdk.py` `*/cli.py` 只许 import 各域的 `shape.py`。**

而 `shape.py` **一行 import 都没有** —— 于是"SDK 要能连别的机器上的服务端"
这条([`the_layout_holds`](../../../tests/the_layout_holds/) 里那条
"给人用的那两个不认识 serve")从"不许 import serve"升级成
"**只许 import 形状**",挡得更靠前。

### 3.2 一件事一个词,三层贯通

CLI 的帮助、API 的字段、观看页那块牌子 —— 三处说同一个词。
今天靠 [`the_layout_holds`](../../../tests/the_layout_holds/) 那条
"三个面里不许出现实现名"守着。

按域分之后这条**更好守**:三处的代码在同一个目录里,
而那个词在 `channel/words.py`([channel §3](channel.md#3-wordspy-不是数据是规则))。

## 4. ↔ 别处

| | |
| --- | --- |
| 一个 server 一个口 | [k](../works/k-one-server.md) |
| 内置页不是"界面" | [e §8](../works/e-client.md) |
| 线上形状 | [api](../api/) |
