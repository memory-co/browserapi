# tab · `TabInfo`

一个 tab。**字段和 `chrome.tabs` 对齐**,便于直接映射
([f §2.1](../works/f-tabs.md#21-那张表的形状))。

## 1. 字段

| 字段 | JSON | 类型 | 说明 |
| --- | --- | --- | --- |
| `id` | `id` | `str` | `t_3` —— **我们分配的,关掉不复用** |
| `index` | `index` | `int` | 在那条 bar 上排第几。`list()` 时填 |
| `active` | `active` | `bool` | **观测值**:浏览器把它放在前台了吗([f §3](../works/f-tabs.md)) |
| `url` | `url` | `str` | |
| `title` | `title` | `str` | |
| `loading` | `loading` | `bool` | |
| `security` | `security` | `str` | `secure` / `neutral` / `insecure` |
| `can_go_back` | `can_go_back` | `bool` | |
| `can_go_forward` | `can_go_forward` | `bool` | |
| `favicon` | `favicon` | `str \| None` | `/api/tabs/t_3/favicon`,**由我们代抓** |
| `opener` | `opener` | `str \| None` | 谁开的它 |
| `reason` | `reason` | `str` | `api` / `page` / `user` —— 判据是 `openerId` |
| `created_at` | `created_at` | `float` | |
| `crashed` | `crashed` | `bool` | |
| `dialog` | `dialog` | `dict \| None` | 挡在这一页上的那个 |
| `target_id` | — | `str` | **不出门:CDP 句柄。** 一重启就全变,给出去等于给一个明天就失效的号 |
| `touched_at` | — | `float` | **不出门:LRU 内部。** 挤 tab 时按它排序 |

`from_json` **有** —— SDK 靠它把 `/api/tabs` 的响应变回对象。

## 2. `index` 和 `active` 是算出来的,不是存的

它们在 `TabTable.list()` 里现填:

```python
t.index, t.active = n, i == self._active
```

所以**单独拿一个 `TabInfo` 出来时这两个字段没意义** —— 它们描述的是
"在那张表里的位置",不是这个 tab 自己的属性。

`to_json(index=…, active=…)` 收这两个参数就是为了这件事:发事件时
(`tab.created`)手上没有整张表,得把它们显式传进去。

## 3. `Tab` 不是 `TabInfo`

> **数据叫 `TabInfo`,能操作的那个叫 `Tab`。**

后者带着 `.click()`、通过 HTTP 干活,住在 [`api.py`](../../../webmuxd/api.py);
它**持有** `TabInfo`,不重新定义一份 —— 对应 requests 里 `Session` 和
`Response` 的关系。

这条区分是 `models.py` 存在的理由的一半:在它之前,同一个 tab 记录服务端一份、
SDK 一份,改一个字段要**记得**改另一边 —— 而"记得"从来不是一种机制。

## 4. `active` 那个字段今天的语义

0.18.0 之前它是"我们记的账",现在是**观测值**:浏览器把哪一页放在前台。
这对 DTO 的影响很具体 ——

> **`active` 不再是"我们打算让谁在前台",而是"现在谁在前台"。**
> 拿到一份 `/api/tabs` 的响应,那个 `active` 和人眼看到的是同一页。

细节和为什么在 [f §3](../works/f-tabs.md)。

## 5. ↔ 别处

| | |
| --- | --- |
| 那张表的规矩 | [f](../works/f-tabs.md) · [api/tabs](../../v1/api/tabs.md) |
| 事件形状 | `tab.created` / `tab.updated` / `tab.activated` / `tab.closed`,见 [f §2.1](../works/f-tabs.md#21-那张表的形状) |
