# page

**Page 没有自己的 id。** 它就是"某个 [tab](tab.md) 现在这一页" ——
换一页,那一页上所有 `@e1` 一律作废。

## 1. HTTP —— 读

### `GET /api/snapshot` → `Snapshot`

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `elements` | `elements` | `Element[]` |
| `notes` | `notes` | 截断之类的提示 —— **截断必须说出来** |
| `filter_version` | `filter_version` | 那套过滤规则的版本 |
| `viewport` | `viewport` | `Size`,即 `{w, h}` |

#### `Element`

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `id` | `id` | **这次观测里的编号**,不跨观测稳定 |
| `role` | `role` | |
| `name` | `name` | **人看得见的那个字** |
| `value` | `value` | |
| `bbox` | `bbox` | `[x,y,w,h]`,出门时 `round(v, 1)` |
| `in_viewport` | `in_viewport` | |
| `enabled` | `enabled` | |
| `affords` | `affords` | 能对它做什么 |
| `hint` | `hint` | |
| `ref` | `ref` | `@e1` —— **跨命令活着的编号**。只有走过 `snapshot` 的才有 |
| `backend_node_id` | — | **不出门:CDP 句柄** |
| `observation` | — | **不出门:只有 SDK 有** —— 这个元素是哪次观测里的 |

`from_json(d, observation="")` 多收一个参数,就是为了填最后那个 ——
**它是 SDK 侧的,不是线上的**。

`id` 和 `ref` 的区别要记死:

> `id` 只在这一次观测里成立;`ref`(`@e1`)跨命令活着。
> 所以紧凑那一行是 **有 ref 就用 `@e1`,没有才退回 `[1]`**。

### `GET /api/text` · `GET /api/screenshot`

正文和一张图。加上上面那张元素表,就是"读的那一面"的全部三样
([i §3](../works/i-agent-surface.md#3-读的那一面一张图正文和一张元素表))。

## 2. HTTP —— 写

### `POST /api/act` → `ActionResult`

**请求**带一串动作,每个动作里可能有一个 `Locator`:

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `ref` `text` `role` `name` `label` `css` | 同名,**空的不出门** | 六种找法 |
| `point` | `point` | `[x, y]` —— **逃生舱**,日志里会被标成 opaque |
| `nth` | `nth` | 有歧义时选第几个 |

空字段一个都不写,所以 `{"role":"link","name":"新闻"}` 线上就是这两个键。

**响应**:

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `ok` `ms` | 同名 | 总是有 |
| `hit` `after` `error` `message` `candidates` `value` | 同名,**空的不出门** | |
| `opaque` | `opaque` | 只有 `True` 才写 |
| `action` | — | **不出门:请求里已经有了** |
| `target` | — | 同上 |

失败那条带 `candidates` 是有意的:**模型据此自我纠正**,
而不是拿到一句"找不到"就卡住。

`from_json` **没有**,而它不是画面下行 —— 按[规矩 3](README.md#4-三条规矩)
这是个待办:**SDK 那边今天在手搓 dict**(`api.ActResult`)。

## 3. 挡着页面的那几样

headless 里没人替你点"保存"、点"允许" —— 所以它们要能被看见和回填。

| 端点 | DTO |
| --- | --- |
| `GET /api/pending` | `Pending[]` |
| `GET /api/downloads` · `GET /api/downloads/{id}` | `Download[]` |
| `POST /api/upload` · `GET /api/files` · `POST /api/file-chooser/{id}` | |
| `GET/POST/DELETE /api/permissions` | |
| `POST/DELETE /api/auth` | |

### `Pending`

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `id` `kind` `tab` `at` | 同名 | `kind` 是五类:对话框 / 下载 / 文件选择 / 权限 / 认证 |
| `info` | **展开进顶层** | 那一类自己的字段 |

和 `LogEntry.fields` 一样的手法。**没有 `from_json`** —— 待办,同上。

### `Download`

`id` `file` `url` `bytes` `total` `state` `path` —— **七个字段全出门**,
一一对应,没有派生也没有隐藏。这批 DTO 里最规矩的一个。

为什么它们必须进得了流水:

> **没有桌面之后,它们是"页面为什么停住"的唯一解释** ——
> 不进 scrollback 的话,现象就只剩"页面一直没变,而且不知道为什么"
> ([g](../works/g-native-ui.md))。

## 4. 事件流

`action.started` / `action.done` / `download.began` / `download.done` /
`auth.required` / `permission.changed`。

它们的载荷进 [`LogEntry.fields`](session.md#3-落盘-logjsonl--logentry) ——
**同一件事在事件流上和在流水里是同一份内容**,只是一个推、一个落盘。

## 5. 不出门的三个

### `Ref` / `RefTable`

`@e1` 那套号。`Ref` 记着 `id` `tab` `backend_node_id` `doc` `role` `name`,
其中 `doc` 是当时那份文档的 `loaderId` —— **这一条最要紧**:

> Chromium 会把 `backendNodeId` **复用给新文档里的节点**,于是导航之后
> 拿旧号去点,`getBoxModel` 照样成功,**点中的是另一个东西,而且不报错**。
> 实测撞到过:首页上的 `@e13` 在搜索结果页上点成功了,点中的是结果页那个搜索框。

所以**页面一换,这个 session 上所有旧号一律作废** —— 这就是
"Page 没有自己的 id"那句话在数据上的样子。

号**只增不重用**:重用是省事,但它把"拿着过期的号去点"从一个**报错**
变成一次**点错东西**。

`RefTable` 本身**不是 DTO**:67 行、三个方法、抛四种 `NotFound`。
它是 `models.py` 里唯一让整个文件需要 `import exceptions` 的东西 ——
除了它和 `_not_found()`,`NotFound` 在那个文件里一处都没用到。

### `PageDigest`

`url` `lines` `alerts` `forms` —— 页面的一份粗略指纹,**只为算出 `after.changed`**。
从不出门,所以没有 `to_json`。

## 6. ↔ 别处

| | |
| --- | --- |
| 读的那一面为什么是这三样 | [i §3](../works/i-agent-surface.md#3-读的那一面一张图正文和一张元素表) |
| 定位规则 | [`tests/pointing_at_things/`](../../../tests/pointing_at_things/) |
| 做一下再看看 | [`tests/doing_and_seeing/`](../../../tests/doing_and_seeing/) |
| `@e1` | [`tests/v2_refs/`](../../../tests/v2_refs/) |
| 挡着页面的那五类 | [g](../works/g-native-ui.md) · [`tests/no_desktop/`](../../../tests/no_desktop/) |
