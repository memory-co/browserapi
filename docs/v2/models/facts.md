# facts · `~/.webmuxd.json`

**这不是配置文件,是机器的事实。** `webmuxd install` 探一遍写下来,
之后所有命令读它。

它是这几张表里**唯一跨"时间"**的:另一头是上一次的自己,而**过去改不了**。

## 1. `MachineFacts`

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `browser` | **`default_browser`** | ⚠ **字段名和键名不一样**,而且没写在别处 |
| `xpra` | `xpra` | |
| `rrweb` | `rrweb` | |
| `xvfb` | `xvfb` | |
| `fonts_dir` | `fonts_dir` | |
| `version` | `version` | `FACTS_VERSION`,今天是 **3** |
| `at` | `at` | 探的时间 |
| `extra` | **展开进顶层** | 认不出的键**原样留着**,写回去时不丢 |

`extra` 那条和 `LogEntry.fields` 是同一个手法,但目的不同:那边是"按类
不同的字段",这边是**"别把别人写的键弄丢"** —— 一份记录可能被更新的版本
写过,旧版本读到不认识的键要原样带回去。

## 2. `None` 不是默认值,是「没探到」

这是整份记录的语义基础:

```
键在   = 探到了
键不在 = 没探到
```

所以 `to_json()` 里 `None` 的字段**一个都不写**(`_drop_empty` 干的),
`from_json()` 里探不到就返回 `None` 而不是一个空对象。

写一个猜的值进去,下次读的人分不清"探到了是空"和"没探过" ——
而这两件要做的事完全相反:前者该报错,后者该去探。

## 3. `FACTS_VERSION` —— 唯一带版本号的一份

> **格式变了,老记录就当没有** —— 重新探,而不是猜字段。

为什么只有它需要版本号:

| | 另一头 | 版本号帮得上忙吗 |
| --- | --- | --- |
| [view](view.md) 那组 | 我们自己写的 TS | 帮不上 —— 两边一起改就行 |
| [tab](tab.md) / [page](page.md) / [session](session.md) | 别人的代码 | 帮不上 —— 规矩是**只加不减**,永远兼容 |
| **这一份** | **过去的自己** | **帮得上** —— 它改不了,只能整份作废 |

猜字段的下场是"读到一个半新半旧的记录,而且每个字段单看都合法"。
整份作废虽然要重探一次,但它**只有一种结果**。

## 4. 三个 Fact 都是 `frozen`

| | 字段 | 说明 |
| --- | --- | --- |
| `BrowserFact` | `path` `version` `source` | `source` 是 `chrome-for-testing`(我们下的)或 `system`(本来就有的) |
| `XpraFact` | `bin` `python` `version` `vfb` | |
| `RrwebFact` | `version` `js` | |

三个都**字段和键一一对应**,而且都有 `from_json`,返回 `None` 表示这一条没探到。

`XpraFact.python` 单记一条不是学究气:

> `xpra` 是带 shebang 的脚本,用的是**系统的** Python,而 webmuxd 很可能
> 装在一个 venv 里 —— `python3-pil` 要装进**它那个**里面。

`XpraFact.vfb` 默认 `"Xvfb"`,**显式钉死,不读发行版配置**。

## 5. `PackageFamily` 不出门

一个发行版家族的包名表:`name` / `install` / `chrome` / `xpra` / `font`。
**包名是唯一真正的差别**,流程是一样的。它只在装的时候用,没有 `to_json`。

## 6. ↔ 别处

| | |
| --- | --- |
| 探什么、装什么 | [d](../works/d-install.md) |
| 谁读谁写 | [`config.py`](../../../webmuxd/config.py) 只读,[`install.py`](../../../webmuxd/install.py) 只写 |
| 测试 | [`tests/installing/`](../../../tests/installing/) |
