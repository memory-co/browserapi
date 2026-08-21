# `/api/*`

全部 JSON,认证同样是 `?t=<token>`。**只读 token 拿不到写操作。**

## 观看端真正用到的那些

```
GET  /api/tabs                         tab 表 + 当前是哪个
POST /api/tabs           {url}         开一个
DELETE /api/tabs/{id}                  关一个
POST /api/tabs/{id}/goto {url}         导航
POST /api/tabs/{id}/back|forward|reload
POST /api/tabs/{id}/dialog {accept, text}
GET  /api/pending                      当前挡着页面的那些
POST /api/file-chooser/{id} {files}
POST /api/upload?name=…                裸字节,回 {files: [...]}
GET  /api/downloads/{id}
GET  /api/view/mode                    能切到哪几种
GET  /api/rrweb.js  /api/rrweb.css     DOM 那条的重放器
```

## 形状

`GET /api/tabs` 回的每一行就是 [`models.TabInfo`](../../../webmuxd/models.py):

```
{id, index, active, url, title, loading, security,
 can_go_back, can_go_forward, favicon, opener, reason,
 created_at, crashed, dialog}
```

`GET /api/observe` 回的是 [`models.Observation`](../../../webmuxd/models.py) ——
观看端不用它,**agent 用**([i](../../../docs/v2/works/i-agent-surface.md))。

## 一条规矩

**观看端不自己造形状。** tab 条画的是 `/api/tabs` 回的东西,
和上层 SDK 拿到的是同一份 —— 内置页是**验链路的**,
它用的接口必须就是别人会用的那些,否则验不出什么。
