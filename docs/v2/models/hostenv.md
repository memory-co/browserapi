# hostenv · 这台机器上探到的东西

**不在那四类里。** `~/.webmuxd.json` 是**这台机器**的事实,
`webmuxd install` 探一遍写下来,比任何 session 都活得久。

它只走一条介质:**落盘**。而它跨的是**时间** —— 另一头是上一次的自己,
**而过去改不了**。

## 1. `HostEnvs`

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `browser` | **`default_browser`** | ⚠ 字段名和键名不一样,没写在别处 |
| `xpra` | `xpra` | |
| `rrweb` | `rrweb` | |
| `xvfb` | `xvfb` | |
| `fonts_dir` | `fonts_dir` | |
| `version` | `version` | `HOSTENV_VERSION`,今天是 **3** |
| `at` | `at` | 探的时间 |
| `extra` | **展开进顶层** | 认不出的键**原样留着**,写回去时不丢 |

`extra` 和 `LogEntry.fields` 是同一个手法,目的不同:那边是"按类不同的字段",
这边是**"别把别人写的键弄丢"** —— 一份记录可能被更新的版本写过,
旧版本读到不认识的键要原样带回去。

## 2. `None` 不是默认值,是「没探到」

整份记录的语义基础:

```
键在   = 探到了
键不在 = 没探到
```

所以 `to_json()` 里 `None` 的字段**一个都不写**,
`from_json()` 里探不到就返回 `None` 而不是一个空对象。

写一个猜的值进去,下次读的人分不清"探到了是空"和"没探过" ——
而这两件要做的事完全相反:前者该报错,后者该去探。

## 3. `HOSTENV_VERSION` —— 唯一带版本号的一份

> **格式变了,老记录就当没有** —— 重新探,而不是猜字段。

为什么只有它需要:

| | 另一头是谁 | 版本号帮得上忙吗 |
| --- | --- | --- |
| [frame](frame.md) 那组 | 我们自己写的 TS | 帮不上 —— 两边一起改 |
| [tab](tab.md) / [page](page.md) / [session](session.md) | **别人的代码** | 帮不上 —— 规矩是**只加不减**,永远兼容 |
| **这一份** | **过去的自己** | **帮得上** —— 它改不了,只能整份作废 |

猜字段的下场是"读到一个半新半旧的记录,而且每个字段单看都合法"。
整份作废虽然要重探一次,但它**只有一种结果**。

## 4. 三个 Fact 都是 `frozen`

| | 字段 | 说明 |
| --- | --- | --- |
| `BrowserEnv` | `path` `version` `source` | `source` 是 `chrome-for-testing`(我们下的)或 `system`(本来就有的) |
| `XpraEnv` | `bin` `python` `version` `vfb` | |
| `RrwebEnv` | `version` `js` | |

三个都**字段和键一一对应**,都有 `from_json`,返回 `None` 表示这条没探到。

`XpraEnv.python` 单记一条不是学究气:

> `xpra` 是带 shebang 的脚本,用的是**系统的** Python,而 webmuxd 很可能
> 装在一个 venv 里 —— `python3-pil` 要装进**它那个**里面。

`XpraEnv.vfb` 默认 `"Xvfb"`,**显式钉死,不读发行版配置**。

## 5. 不出门:`PackageFamily`

一个发行版家族的包名表:`name` / `install` / `chrome` / `xpra` / `font`。
**包名是唯一真正的差别**,流程是一样的。只在装的时候用,没有 `to_json`。

## 6. 谁读谁写

> [`config.py`](../../../webmuxd/config.py) **只读**,
> [`install.py`](../../../webmuxd/install.py) **只写**。

一份记录两处都能写,迟早会有一处写了另一处不知道。

## 7. ↔ 别处

| | |
| --- | --- |
| 探什么、装什么 | [d](../works/d-install.md) |
| 测试 | [`tests/installing/`](../../../tests/installing/) |
