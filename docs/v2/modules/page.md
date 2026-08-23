# page · 在一页里找东西、做事、看结果

**一句话**:这个域是 agent 那一面的全部 —— **按人看得见的字找,做一下,
然后说变了什么**([i](../works/i-agent-surface.md))。

## 1. 今天散在哪

| 今天 | 多大 | 干什么 |
| --- | --- | --- |
| `locate.py` | 373 | 按 role/name/label 找,分档匹配,有歧义列候选 |
| `act.py` | 857 | 一串动作按序执行、遇错即停、settle 之后说一句人话 |
| `capture.py` | 59 | 抓正文 / 抓图 |
| `models.py` 里 `Element` `Snapshot` `Size` `Locator` | ~190 | 形状 |
| `models.py` 里 `RefTable` `Ref` `_not_found` | **83** | `@e1` 那套号 —— **它不是形状** |
| `models.py` 里 `ActionResult` `PageDigest` | 31 | 形状 |
| `serve.py` 里 `h_act` `h_snapshot` `h_screenshot` `h_text` | | HTTP |
| `api.py` 里 `Tab` 上那 49 个方法的大半 | | SDK |
| `cli.py` 里 `cmd_click` `cmd_type` `cmd_get` `cmd_is` `cmd_snapshot` `cmd_capture` `_locator` `_do` | | 命令 |

## 2. 该长成什么样

```
page/
  README.md
  shape.py     Element / Snapshot / Size / Locator / ActionResult / PageDigest
  find.py      定位:分档匹配、歧义、候选
  refs.py      `@e1` 那套号 —— **有状态,所以它不在 shape.py**
  act.py       动作:按序、遇错即停、settle
  see.py       抓正文、抓图
  http.py      /api/act · /api/snapshot · /api/capture
  sdk.py  cli.py
```

## 3. `RefTable` 为什么必须离开形状那一侧

它今天在 `models.py` 里,**67 行、3 个方法、抛四种 `NotFound`**。
而 `models.py` 开头第一条规矩写着"只有数据,没有行为"。

它不是有人某天决定把服务塞进模型层。看它长成的路径:

> 加一个字段 → 加一个方法 → 那个方法要报错 → import 一下 `exceptions` →
> 四种失败分开说 → 67 行。

**每一步单独看都合理,而且中间没有任何一步会红。**

更值钱的一个发现:`models.py` 那条"不 import 本项目任何东西(**除 `exceptions`**)"
里的例外,**唯一的原因**就是它和 `_not_found()` —— 除此之外一处都没用到。
搬进 `page/refs.py` 之后,规矩 3(`shape.py` 一行 import 都没有)自动挡住这类漂移。

## 4. 那套号里最值钱的一条实测

`refs.py` 里那段注释要原样带走:

> Chromium 会把 `backendNodeId` **复用给新文档里的节点**,于是导航之后
> 拿旧号去点,`getBoxModel` 照样成功,**点中的是另一个东西,而且不报错**。
> 实测撞到过:首页上的 `@e13` 在搜索结果页上点成功了,点中的是结果页那个搜索框。

所以号带 `loaderId`,页面一换全作废。**号只增不重用** ——
重用是省事,但它把"拿着过期的号去点"从一个**报错**变成一次**点错东西**。

## 5. `native` 是同一个域的边角

浏览器自己弹的那五类(对话框 / 下载 / 文件选择 / 权限 / 认证)——
`browser_ui.py`(547)加上 `models` 里的 `Pending` `Download`。

它们和 `page` 是一件事吗?**判据用"会不会一起改"**:
它们回答的是同一个问题的两半 —— "页面为什么停住了"。
一个是页面自己的状态,一个是浏览器盖在页面上的东西。

倾向:**单独一个 `native/`**,因为它有自己的一条硬规矩,和 page 的不一样:

> **没有桌面之后,它们是"页面为什么停住"的唯一解释** ——
> 不进 scrollback 的话,现象就只剩"页面一直没变,而且不知道为什么"
> ([g](../works/g-native-ui.md))。

## 6. ↔ 别处

| | |
| --- | --- |
| agent 那一面 | [i](../works/i-agent-surface.md) |
| 定位规则 | [`tests/pointing_at_things/`](../../../tests/pointing_at_things/) |
| 做一下再看看 | [`tests/doing_and_seeing/`](../../../tests/doing_and_seeing/) |
| `@e1` | [`tests/v2_refs/`](../../../tests/v2_refs/) |
| 原生 UI | [g](../works/g-native-ui.md) · [`tests/no_desktop/`](../../../tests/no_desktop/) |
