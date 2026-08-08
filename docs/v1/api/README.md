# webmuxd v1 · HTTP 接口规格

设计稿在 [`../works`](../works/)。这里是**线上格式**:非 Python 的 client 照这个来,
调试的时候 `curl` 也照这个来。

**行为不定义在这儿。** 定位规则、元素筛选、`candidates`、日志格式都定义在
[`../sdk`](../sdk/) 那个 lib 里,本目录是它的**导出面** —— 为什么这么定,
见 [works/02](../works/02-lib-and-api.md)。所以本目录只描述线上长什么样;
遇到「为什么是这个语义」的问题,答案在 sdk 那边。命令行在 [`../cli`](../cli/)。

本文与 [tabs](tabs.md)/[act](act.md)/[log](log.md)/[events](events.md) 讲的是**单个 session**;
[server.md](server.md) 讲的是**管理多个 session**。

| 文件 | 内容 | 主体在 | 命令行 |
| --- | --- | --- | --- |
| README.md(本文) | 全局约定、端点总表、错误 | [sdk](../sdk/README.md) | [cli](../cli/README.md) |
| [tabs.md](tabs.md) | tab 的增删改查、导航、历史、favicon | [sdk](../sdk/tab/README.md) | [cli](../cli/tabs.md) |
| [act.md](act.md) | 在页面上**做**和**看** —— 动作、定位、观测 | [sdk](../sdk/tab/input.md) | [cli](../cli/act.md) |
| [log.md](log.md) | 操作日志 | [sdk](../sdk/log.md) | [cli](../cli/log.md) |
| [events.md](events.md) | WS 事件字典 | [sdk](../sdk/events.md) | [cli](../cli/events.md) |
| [server.md](server.md) | session 管理、代理、鉴权 | [sdk](../sdk/session.md) | [cli](../cli/server.md) |

## 1. 约定

**Base**:`http://<host>:7900/api` —— 直连某个 session。
经 server 代理时是 `http://<host>:7800/s/<name>/api`,**`/api` 之后的部分完全一样**
([server.md §2](server.md))。查看页面和 API 同一个 origin,不用管跨域。

**认证**:设了 `WEBMUXD_TOKEN` 就带 `Authorization: Bearer <token>`,没设就不用。

另有一个只读 token `WEBMUXD_VIEW_TOKEN`:能看画面、能读 `GET` 接口,**所有 `POST`/`DELETE` 返回 `403 read_only`**。
把观看链接发给别人时用这个。

**内容类型**:请求响应都是 `application/json`,截图和 favicon 例外(直接返回图片字节)。

**幂等**:`POST` 接受 `Idempotency-Key` 头,10 分钟窗口内重放返回原结果。
`POST /api/act` 尤其要用——网络重试导致的重复点击是真实事故。

**并发**:**一个 session 同时只跑一个动作**。并发调 `/api/act` 返回 `409 busy`,不排队、不交错。
要真并发就多起几个 session。

## 2. 一条贯穿全局的规则:tab 参数

**所有页面级操作都接受一个可选的 `tab` 参数,不传就作用在当前激活的 tab 上。**

```jsonc
POST /api/act  { "actions": [...] }                // 当前 tab
POST /api/act  { "tab": "t_7", "actions": [...] }  // 指定 tab
GET  /api/observe                                   // 当前 tab
GET  /api/observe?tab=t_7                           // 指定 tab
```

Agent 平时不用关心 tab;需要跨 tab 操作时再指定。

**对非激活 tab 的输入是可以的**——CDP 的输入投递给 target,不走屏幕焦点,
所以后台 tab 照样能点。但 VNC 画面只显示激活的那个,所以后台操作**人看不见**,
日志里会标 `background: true`。

**要像素的接口是例外。** Chrome 不渲染后台 tab,所以 `GET /api/observe` 和
`GET /api/screenshot` 指向非激活 tab 时,sessiond **会先把它切到前台再拍**
(响应里带 `activated: true`,并发一条 `tab.activated` 事件)。
不这么做就只能拿到空白或上一帧,而"截图和人看到的画面对不上"是这东西最不能出的错。

## 3. 端点总表

### tab bar —— 详见 [tabs.md](tabs.md)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/tabs` | 全部 tab |
| `POST` | `/api/tabs` | 新建 |
| `GET` | `/api/tabs/{id}` | 单个 tab |
| `POST` | `/api/tabs/{id}/activate` | 切过去 |
| `DELETE` | `/api/tabs/{id}` | 关闭 |
| `POST` | `/api/tabs/{id}/goto` | 导航 |
| `POST` | `/api/tabs/{id}/back` `/forward` `/reload` `/stop` | 前进后退刷新停止 |
| `GET` | `/api/tabs/{id}/history` | 历史条目,用来画前进后退长按菜单 |
| `POST` | `/api/tabs/reorder` | 拖拽排序 |
| `GET` | `/api/tabs/{id}/favicon` | 图标字节 |

### 页面上的动作与观测 —— 详见 [act.md](act.md)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/observe` | **观测**:标注截图 + 元素表 + tab 列表 |
| `POST` | `/api/act` | **执行动作**(单个或一串) |
| `GET` | `/api/screenshot` | 截图,`?full_page=` 要整页 |
| `GET` | `/api/text` | 页面正文 |
| `GET` | `/api/log` | 操作日志,详见 [log.md](log.md) |
| `GET` | `/api/log/bundle` | 日志 + 截图 + 离线 HTML 的 zip |
| `POST` | `/api/upload` | 传文件进去给 `upload` 动作用 |
| `GET` | `/api/download/{name}` | 取下载的文件 |

### session 级

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/status` | Chrome 活着没、当前 tab、版本 |
| `GET` | `/api/viewport` | 屏幕尺寸与 `crop_top`(外面裁 iframe 用) |
| `POST` | `/api/reset` | 清 cookie、关多余 tab、回 about:blank |
| `POST` | `/api/live-token` | 签发观看页面的一次性 token,`{ "read_only": true, "ttl_s": 3600 }` |
| `GET` | `/api/openapi.json` | 由 lib 的方法签名生成,不手写 |
| `WS` | `/api/events` | 事件流,见 [events.md](events.md) |

```jsonc
// GET /api/status
{ "ok": true, "chrome": { "alive": true, "version": "139.0.7258.154", "restarts": 0 },
  "active_tab": "t_3", "tab_count": 3,
  "screen": { "w": 1024, "h": 768 }, "crop_top": 88,
  "uptime_s": 4210, "log_count": 142, "busy": false }

// GET /api/viewport
{ "screen": {"w":1024,"h":768}, "crop_top": 88, "page": {"w":1024,"h":680} }
```

`crop_top` 会变(视频全屏归零、开书签栏变大),变了会发 `viewport.changed` 事件。
外面的 iframe 按它重新裁,见 [works/04 §2](../works/04-chrome-ui-externalization.md)。

## 4. 错误

```jsonc
{ "error": { "code": "not_found",
             "message": "找不到「提交订单」",
             "details": { "candidates": [ {"role":"button","name":"提交订单(2)"}, ... ] } } }
```

| code | HTTP | 意思 | 调用方该干嘛 |
| --- | --- | --- | --- |
| `not_found` | 404 | 定位不到元素,**带候选** | 换个写法,或把候选喂回模型 |
| `not_clickable` | 409 | 找到了但被遮挡/禁用 | 等一下重试,或先滚动 |
| `timeout` | 408 | settle 或 wait_for 超时 | 重试或放宽条件 |
| `nav_failed` | 502 | 页面打不开 | 检查 URL / 网络 |
| `tab_gone` | 404 | tab 已经关了 | 重新拉 `/api/tabs` |
| `busy` | 409 | 已有动作在跑 | 等,或多起几个 session |
| `busy_human` | 409 | 人正在 VNC 里操作 | 见 §5 |
| `read_only` | 403 | 用的是只读 token | — |
| `chrome_gone` | 503 | Chrome 崩了(会自动重拉) | 等重启,别盲目重试动作 |
| `blocked_url` | 400 | 特权页面(`chrome://` 那类),禁止导航 | 别去,见 [tabs.md §3](tabs.md#3-写) |
| `bad_request` | 400 | 参数不对 | 改代码 |

前五个是**调用方能自愈**的;`chrome_gone` 是这个 session 出事了,该告警而不是重试。

这张表是 lib 那棵异常树的序列化([sdk/README §3](../sdk/README.md#5-异常)) ——
`code` 对应类名,`details` 装的是异常上那些属性(`candidates`、`retry_after_ms`、`hint`)。
CLI 再把同一个二分压成退出码([cli/README §6](../cli/README.md#6-退出码))。

## 5. 人在操作时的让路

人在 VNC 里点了东西之后的 `WEBMUXD_HUMAN_YIELD` 毫秒内(默认 3000),
API 动作返回 `409 busy_human` 并带 `retry_after_ms`。

```jsonc
{ "error": { "code": "busy_human", "message": "人正在操作",
             "details": { "retry_after_ms": 2400 } } }
```

设 `WEBMUXD_HUMAN_YIELD=0` 关掉这个行为,谁快谁先。
不做显式的「接管/交还」开关——人点人的,API 跑 API 的,两边都进日志。

## 6. 版本

路径里没有版本号,靠 `GET /api/status` 的 `api` 字段:

```jsonc
{ "api": { "version": "1.0", "schema": "v1" } }
```

字段只增不删不改语义。要破坏兼容时才上 `/api/v2`。

**版本跟着 lib 走**:导出面是从 lib 的方法签名生成的,所以这里不会先于 lib 出现新字段。
反过来,lib 加了纯客户端的东西(`with`、`obs[12]`)不影响这个版本号 —— 没导出就不算变更。
