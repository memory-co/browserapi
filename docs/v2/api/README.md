# v2 · api

**一个 server 一个口。** 画面、API、全部 session 都在它上面。

```
GET  /                        那张 session 列表(内置页)
GET  /s/<id>/                 那个 session 的画面(内置页)
GET  /s/<id>/api/*            那个 session 的 API
GET  /s/<id>/channel/*        那个 session 的画面通道
GET  /api/sessions            server 自己那一层
```

> **相对 [v1/api](../../v1/api/) 变了三处**,其余(tab、act、log、错误模型)
> 一个字没动,仍以 v1 那份为准:
>
> 1. **路径多一段 `/s/<id>/`**,并新增 server 那一层(§1)
> 2. **读是三个口子**,`GET /api/observe` 那个「一包全给」的形状没了(§3)
> 3. **画面走 WS**,三条通道(§4)

## 1. server 那一层

```
GET    /api/sessions              有哪些
POST   /api/sessions  {id, ...}   建一个(同一个 id 再来一次就是接管)
DELETE /api/sessions/{id}         关一个
GET    /api/server                版本 / 几个 session / uptime
DELETE /api/server                `server stop` —— 一个都不留,然后自己也走
GET    /healthz                   探活
```

`GET /api/sessions` 里的每一行是
[`models.SessionRow`](../../../webmuxd/models.py):

```jsonc
{ "id": "work", "runtime": "process", "url": "/s/work/",
  "tabs": 3, "active_tab": "t_1",
  "view": "vnc", "view_label": "VNC",        // 实现名 + 界面上那个词
  "available": ["vnc", "jpg", "dom"],
  "uptime_s": 812, "notes": [] }
```

**列表页、`webmuxd ls`、这个端点用的是同一份** —— 不是三处各拼一遍。

**认不出的 `<id>` 回 404,不猜。**

## 2. session 那一层

路径前面加 `/s/<id>`,其余和 [v1/api](../../v1/api/) 完全一样:

```
GET    /s/work/api/tabs                    POST /s/work/api/act
POST   /s/work/api/tabs {url}              GET  /s/work/api/log
DELETE /s/work/api/tabs/{id}               GET  /s/work/api/pending
POST   /s/work/api/tabs/{id}/goto {url}    …
```

**这一段是纯前缀。** 服务端所有 handler 拿 session 走同一个入口
(`_s(request)`),所以"哪个 session"只在那一处回答
([k §4](../works/k-one-server.md#4-路由sid-前缀))。

## 3. 读:一张图、正文、一张元素表

```
GET /s/work/api/screenshot?full_page=false   → image/webp
GET /s/work/api/text                         → text/plain
GET /s/work/api/snapshot                     → application/json
        ?interactive=1     只要能点能填的
        &selector=%23main  只看这棵子树
        &viewport=1        只要视口内的
        &max=150           最多几个
```

前两个直接回字节;`snapshot` 回一张元素表,**每样带一个 `@e1`**:

```jsonc
{"elements": [{"ref": "e13", "role": "textbox", "name": "", "value": "",
               "bbox": [242, 195, 771, 28], "in_viewport": true,
               "enabled": true, "affords": ["type", "clear"]}],
 "notes": [], "filter_version": 2, "viewport": {"w": 1024, "h": 768}}
```

号存在 session 里,跨命令有效,**只增不重用** ——
第二次 `snapshot` 从 `@e14` 接着发,拿过期的号来点会报错,
不会指向另一个元素([i §3.2](../works/i-agent-surface.md#32-编号这次是怎么解决的))。

`GET /api/observe` 那个「一次调用回一整包」的形状没有回来 ——
截图、正文、元素表是三件事,要哪样取哪样。
那几个筛选旋钮也不再写死在库里:**意见留在调用方那边**,
是当初砍它时说对了的那一半。

`screenshot` 对非激活 tab 会**先切前台**(Chromium 不渲染后台 tab),
而且它**一声不吭地切,也不和 `act` 排队** ——
已知的口子,见 [issue](../issues/读一眼会改状态却不排队.md)。

**定位多了一种,`{"ref": "e13"}`** —— 它是 `snapshot` 发的号,最准。
老那种 `{"element": 12, "observation": "..."}` 没有回来:
那是靠一个观测 id 去挡陈旧编号,而现在**号本身全局唯一**,不需要那条元数据。
定位失败回的候选带着 `role` + `name`(有号的话也带上 `ref`),
**那才是跨快照仍然成立的说法**。

## 4. 画面:三条通道

| 路径 | 方向 | 传什么 |
| --- | --- | --- |
| `/s/work/channel/cdp` | **双向** | JPG 帧(28 字节头 + 裸字节)+ 下行 JSON;**所有输入从这条上去** |
| `/s/work/channel/xpra` | 双向 | xpra 协议裸包 |
| `/s/work/channel/rrweb` | **只下行** | rrweb 事件 |
| `/s/work/api/events` | 只下行 | tab 变化、对话框、下载 |

逐字节的格式在 [`webmuxjs/server/protocol/`](../../../webmuxjs/server/protocol/) ——
那份文档不属于任何一种语言,今天由 Python 实现。

下行那六种消息(`hello` / `cast` / `meta` / `quality` / `mode` / `mode_error` /
`cursor`)的形状在 [`models.py`](../../../webmuxd/models.py),
和 `protocol/messages.ts` 一一对应。**每条都带 `type`** ——
观看端按它分流,漏了就是静默失效。

## 5. 鉴权

`?t=<token>`,或 `Authorization: Bearer`。**只读 token 的写操作 403。**

token 会进历史和 Referer,所以内置页拿到手第一件事是
`history.replaceState` 抹掉。

## 6. ↔ 别处

| | |
| --- | --- |
| tab / act / log / 错误模型 | [v1/api](../../v1/api/) —— 那部分没变 |
| Python 那一面 | [sdk](../sdk/) |
| 命令行 | [cli](../cli/) |
| 线上逐字节 | [`webmuxjs/server/protocol/`](../../../webmuxjs/server/protocol/) |
