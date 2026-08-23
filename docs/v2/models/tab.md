# tab

**一个 tab = 浏览器 target 表里的一行**,加上一个我们分配的稳定编号。
它属于某个 [session](session.md);它当前那一页是 [page](page.md)。

## 1. HTTP

| 端点 | 收什么 | 回什么 |
| --- | --- | --- |
| `GET /api/tabs` | — | `{tabs: TabInfo[], active: str}` |
| `POST /api/tabs` | `{url, active?}` | `TabInfo` |
| `GET /api/tabs/{id}` | — | `TabInfo` |
| `DELETE /api/tabs/{id}` | — | `{closed, created?, active}` |
| `POST /api/tabs/{id}/activate` | — | `TabInfo` |
| `POST /api/tabs/reorder` | 顺序 | |
| `GET /api/tabs/{id}/history` | — | 前进后退 |
| `POST /api/tabs/{id}/{back\|forward\|reload\|stop\|goto}` | | |
| `POST /api/tabs/{id}/dialog` | 回填 | |

### `TabInfo`

**字段和 `chrome.tabs` 对齐**,便于直接映射
([f §2.1](../works/f-tabs.md#21-那张表的形状))。

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `id` | `id` | `t_3` —— **我们分配的,关掉不复用** |
| `index` | `index` | 在那条 bar 上排第几 |
| `active` | `active` | **观测值**:浏览器把它放在前台了吗 |
| `url` | `url` | |
| `title` | `title` | |
| `loading` | `loading` | |
| `security` | `security` | `secure` / `neutral` / `insecure` |
| `can_go_back` | `can_go_back` | |
| `can_go_forward` | `can_go_forward` | |
| `favicon` | `favicon` | `/api/tabs/t_3/favicon` —— **由我们代抓** |
| `opener` | `opener` | 谁开的它 |
| `reason` | `reason` | `api` / `page` / `user`,判据是 `openerId` |
| `created_at` | `created_at` | |
| `crashed` | `crashed` | |
| `dialog` | `dialog` | 挡在这一页上的那个 |
| `target_id` | — | **不出门:CDP 句柄。** 一重启就全变,给出去等于给一个明天失效的号 |
| `touched_at` | — | **不出门:LRU 内部**,挤 tab 时按它排序 |

`index` 和 `active` 是 `TabTable.list()` 现填的,不是存的 ——
**单拿一个 `TabInfo` 出来时这两个字段没意义**,它们描述的是"在那张表里的位置"。
所以 `to_json(index=…, active=…)` 收这两个参数:发 `tab.created` 事件时
手上没有整张表。

## 2. 事件流

| 事件 | 带什么 |
| --- | --- |
| `tab.created` | `{tab: TabInfo, reason}` |
| `tab.updated` | `{id, changed: {…}}` —— **只发变化的字段** |
| `tab.activated` | `{id, previous}` |
| `tab.closed` | `{id, active, reason, final_url}` |

`tab.updated` 只发变化的字段,是因为**整条替换会让外面的 tab 条闪、
丢掉滚动位置**。

`tab.closed` 的 `reason` 分得清**你关的**(`closed`)和**被挤掉的**(`evicted`)
—— 后者不是任何人的意图,是超了上限被 LRU 挤出去的,所以它还带 `final_url`
让调用方能重开。

## 3. 画面上行:`{"type":"tab","id":"t_3"}`

观看页点那条 bar 走的是**上行消息,不是 HTTP**:

> 它要和画面同一条路,否则会错序。

九种上行里唯一一条 tab 相关的。

## 4. `active` 是观测值,不是账

0.18.0 之前它是"我们记的账",现在是**浏览器把哪一页放在前台**。
对 DTO 的影响很具体:

> 拿到一份 `/api/tabs` 的响应,那个 `active` 和**人眼看到的是同一页**。

也因此 `POST /api/tabs/{id}/activate` **会阻塞到确认为止** ——
返回即为真;确认不了回 `tab_not_front`(409),不悄悄当它成了。

## 5. `Tab` 不是 `TabInfo`

> **数据叫 `TabInfo`,能操作的那个叫 `Tab`。**

后者带着 `.click()`、通过 HTTP 干活,住在 [`api.py`](../../../webmuxd/api.py);
它**持有** `TabInfo`,不重新定义一份 —— 对应 requests 里 `Session` 和
`Response` 的关系。

这条区分是这批 DTO 存在的理由的一半:在它之前,同一个 tab 记录服务端一份、
SDK 一份,改一个字段要**记得**改另一边 —— 而"记得"从来不是一种机制。

## 6. ↔ 别处

| | |
| --- | --- |
| 那张表的规矩 | [f](../works/f-tabs.md) · [api/tabs](../../v1/api/tabs.md) |
| 前台是谁 | [`tests/who_is_in_front/`](../../../tests/who_is_in_front/) |
