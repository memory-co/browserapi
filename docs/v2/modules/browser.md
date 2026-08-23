# browser · 弄来一个能连的 Chromium

**一句话**:这个域只回答一件事 —— **给我一个 CDP 端点**。
怎么来的(本机起一个 / 连一个远端的)是它的内部事务。

## 1. 今天散在哪

| 今天 | 多大 | 干什么 |
| --- | --- | --- |
| `processes.py` | 321 | 起、等口、看活、收干净;`forget_last_tabs` |
| `cdp.py` | 240 | 一条到 Chromium 的连接 |
| `config.py` | 229 | 读那份路径表、探浏览器、缺哪些 so |
| `sessions.py` 里 `ProcessRuntime` | 211 | 起 chrome / 起 xpra,拼那一长串参数 |
| `sessions.py` 里 `RemoteRuntime` | 52 | 连一个别人的端点 |
| `sessions.py` 里 `resolve_transport` `default` `get` `detect` | ~47 | 选哪条 runtime |

**`ProcessRuntime` 住在 `sessions.py` 里,是上一次摊平时被逼过去的**
([j §7](../works/j-layout.md)):它要起 xpra、要找浏览器,而那两样一个在
第 2 层一个在第 5 层,只能往上挪。**那不是它该在的地方,是层表算出来的位置。**

## 2. 该长成什么样

```
browser/
  README.md    一句话
  shape.py     SessionInfo(runtime 产出的那个把柄)
  cdp.py       一条连接
  process.py   本机起一个:进程、参数、等口、收干净
  remote.py    连一个别人的
  pick.py      选哪条 runtime、resolve_transport
```

## 3. 里面那条最硬的规矩

> **不可用就抛,不降级。**

`--transport vnc` 而机器上没有 xpra,**不悄悄退回 JPG** —— 报出来,
并说该跑哪一行([h](../works/h-runtime.md))。这条今天就在,
搬家不改变它,但它终于和它管的那些代码在一起了。

### 3.1 `SessionInfo.detail` 要收拾

今天它是 `dict[str, Any]`,而**里面装着一个活的子进程**:

```python
sess = handle.detail["_xpra"]   # xpra 那个 Popen
sess.proc.poll()
```

它今天在 `models.py` 里,而 `models.py` 开头写着"只有数据,没有行为"。
**搬进 `browser/shape.py` 会立刻违反规矩 3(一行 import 都没有)** ——
那正是要的效果:它不是形状,它是把柄。

拆的时候得回答:**把柄里到底有哪几样,能不能写成字段。**
今天那个袋子里有 `cdp` `cdp_port` `work` `browser` `transport` `display`
`xpra_ws` `xpra_ws_port` `xpra_log` `view` `pids` `notes` `_xpra` ——
前十二个是数据,最后一个不是。

## 4. `install` 是同一个域的另一半

**探、下、装、记**([d](../works/d-install.md))和"弄来一个能连的浏览器"
是同一件事的两个时刻:`install` 是一次性的,`browser` 是每次都要的。

分成两个目录还是一个,判据用 §1 那条:**它们会一起改吗。**
共改数据说会 —— `install` 写那份 `~/.webmuxd.json`,`config` 读它,
而 `browser/process.py` 用它。

```
install/
  README.md
  shape.py     MachineFacts / BrowserFact / XpraFact / RrwebFact / FACTS_VERSION
  probe.py     探:浏览器、xpra、字体、缺哪些 so
  fetch.py     下:chrome-for-testing、rrweb
  record.py    记:`~/.webmuxd.json` 的读写
```

那份记录有一条别处没有的规矩,**值得单独说**:

> **`None` = 没探到,不是"默认值"。** 键在 = 探到了,键不在 = 没探到。
> 所以 `to_json()` 里 `None` 的字段一个都不写。

以及:**格式变了老记录就当没有**(`FACTS_VERSION`)—— 重新探,而不是猜字段。
这是四类跨边界数据里**唯一有版本号的一类**,因为只有它的另一头
(过去的自己)改不了。

## 5. ↔ 别处

| | |
| --- | --- |
| runtime 只做一件事 | [h](../works/h-runtime.md) · [`tests/one_endpoint/`](../../../tests/one_endpoint/) |
| 探什么装什么 | [d](../works/d-install.md) · [`tests/installing/`](../../../tests/installing/) |
