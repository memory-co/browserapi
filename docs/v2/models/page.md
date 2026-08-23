# page · 页面上那些东西

`Element` `Snapshot` `Size` `Locator` `ActionResult`,加上不出门的
`Ref` `RefTable` `PageDigest`。

## 1. `Element` —— 一个能被定位到的东西

| 字段 | JSON | 类型 | 说明 |
| --- | --- | --- | --- |
| `id` | `id` | `int` | **这次观测里的编号**,不跨观测稳定 |
| `role` | `role` | `str` | |
| `name` | `name` | `str` | **人看得见的那个字** |
| `value` | `value` | `str \| None` | |
| `bbox` | `bbox` | `[x,y,w,h]` | 出门时 `round(v, 1)` |
| `in_viewport` | `in_viewport` | `bool` | |
| `enabled` | `enabled` | `bool` | |
| `affords` | `affords` | `list[str]` | 能对它做什么 |
| `hint` | `hint` | `str` | |
| `ref` | `ref` | `str` | `@e1` —— **跨命令活着的编号**,由 `RefTable` 发。只有走过 `snapshot` 的才有 |
| `backend_node_id` | — | `int \| None` | **不出门:CDP 句柄** |
| `observation` | — | `str` | **不出门:只有 SDK 有** —— 这个元素是哪次观测里的 |

`from_json(d, observation="")` 多收一个参数,就是为了把最后那个字段填上 ——
**它是 SDK 侧的,不是线上的**。

`id` 和 `ref` 的区别值得说死:

> `id` 只在这一次观测里成立;`ref`(`@e1`)跨命令活着。
> 所以 `as_line()` 是 **有 ref 就用 `@e1`,没有才退回 `[1]`**。

## 2. `Snapshot` / `Size`

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `elements` | `elements` | `Element` 的列表 |
| `notes` | `notes` | 截断之类的提示 —— **截断必须说出来** |
| `filter_version` | `filter_version` | 那套过滤规则的版本 |
| `viewport` | `viewport` | `Size`,即 `{w, h}` |

`Size` 只有 `w` / `h` 两个字段,但它有 `__eq__` 能和一对数比:
`o.viewport == (1015, 676)` 是最自然的写法。

## 3. `Locator` —— 怎么找一个元素

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `ref` `text` `role` `name` `label` `css` | 同名,**空的不出门** | 六种找法 |
| `point` | `point` | `[x, y]` —— **逃生舱**,而且它在日志里会被标成 opaque |
| `nth` | `nth` | 有歧义时选第几个 |

**空字段一个都不写**。所以一个 `{"role":"link","name":"新闻"}` 的 locator
线上就是这两个键,不会带一堆 `null`。

## 4. `ActionResult` —— 做完一下之后

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `ok` | `ok` | 总是有 |
| `ms` | `ms` | 总是有 |
| `hit` `after` `error` `message` `candidates` `value` | 同名,**空的不出门** | |
| `opaque` | `opaque` | 只有 `True` 时才写 |
| `action` | — | **不出门:请求里已经有了**,响应里再回一遍是冗余 |
| `target` | — | 同上 |

`from_json` **没有** —— 而它不是下行消息。按
[README §2 第 3 条](README.md#2-三条规矩)这是个待办:
**SDK 那边今天在手搓 dict**(`api.ActResult`)。

失败那条带 `candidates`,是有意的:**模型据此自我纠正**,
而不是拿到一句"找不到"就卡住。

## 5. 不出门的三个

### `Ref` / `RefTable`

`@e1` 那套号。`Ref` 记着 `id` `tab` `backend_node_id` `doc` `role` `name` ——
其中 `doc` 是那时候文档的 `loaderId`,**这一条是最要紧的**:

> Chromium 会把 `backendNodeId` **复用给新文档里的节点**,于是导航之后
> 拿旧号去点,`getBoxModel` 照样成功,**点中的是另一个东西,而且不报错**。
> 实测撞到过:首页上的 `@e13` 在搜索结果页上点成功了,点中的是结果页那个搜索框。

`RefTable` **不是 DTO**:67 行、三个方法、抛四种 `NotFound`。
它是这个文件里唯一让 `models.py` 需要 `import exceptions` 的东西 ——
除了它和 `_not_found()`,`NotFound` 在整个文件里一处都没用到。

### `PageDigest`

`url` `lines` `alerts` `forms` —— 页面的一份粗略指纹,**只为算出 `after.changed`**。
它从不出门,所以没有 `to_json`。

## 6. ↔ 别处

| | |
| --- | --- |
| 读的那一面为什么是这三样 | [i §3](../works/i-agent-surface.md#3-读的那一面一张图正文和一张元素表) |
| 定位规则 | [`tests/pointing_at_things/`](../../../tests/pointing_at_things/) |
| `@e1` | [`tests/v2_refs/`](../../../tests/v2_refs/) |
