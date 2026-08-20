# 把行为流导成 Playwright trace

**这是原型,不是 webmuxd 的功能。** 它验的是
[c §16](../../docs/v2/works/c-view.md#16-playwright-trace不是来源是产物)
那张映射表能不能落地 —— 结论是能,连带量出六个具体问题(见下)。

```bash
python3 examples/trace_export/demo.py            # 写出 ./webmuxd-trace.zip
npx playwright show-trace webmuxd-trace.zip      # 打开
```

也可以拖进 https://trace.playwright.dev/(纯前端,文件不上传)。

## 它做了什么

起一个真 session,在一个表单页上做五件事(**其中一条故意点不存在的东西**),
每条动作**前后各拉一张 DOM 快照、动作后截一张图**,然后写成 trace.zip。

打开之后能看到:左侧动作列表(失败那条是红的)、中间是可交互的 DOM 回放、
顶上是 filmstrip 和**播放按钮**,右下是参数和耗时。

| trace 要什么 | 从哪来 |
| --- | --- |
| `before` / `input` / `after` | `log.jsonl` 里 `kind=="action"` 的行 |
| 动作标题 | `[谁] 动词 目标` —— **trace 没有「谁做的」这个字段,只能塞进标题** |
| `input.point`(回放里那个点击光标) | `hit.bbox` 取中心 |
| 失败 | `ok:false` → `after.error`,列表里显示成红的 |
| `frame-snapshot` | `snapshot.js` 在**我们自己的动作边界**上拉的全量 DOM |
| `screencast-frame` | `tab.screenshot()` |

**动作边界是这件事的关键。** Playwright 自己录不到我们的动作 ——
我们的输入是裸 CDP `Input.dispatchMouseEvent`,不构成 Playwright 调用
([c §16](../../docs/v2/works/c-view.md#16-playwright-trace不是来源是产物))。
而边界本来就是我们定义的,所以只要在那个位置调一次序列化就行。

## 量到的问题

做出来之后才看得见的,按要不要动现有代码排:

| | |
| --- | --- |
| **`log.jsonl` 的 `at` 只到秒** | 时间轴需要毫秒,否则同一秒里的几条动作叠在一起、看不出先后。这里靠「上一条的结束时间」兜底保证递增,**是编的,不是量的** |
| **内部重试会落成独立的 action 条目** | 一次 `tab.type()` 失败后自动重试,日志里是两条,导出后就成了两步。trace 有 `parentId` 可以归组,而我们的日志现在**没有父子关系** |
| **`shots/` 没人写** | `log.shot_path(seq)` 有读的地方(`/api/log/{seq}/shot`),没有写的地方 —— 「每条动作存一帧」还没做,这里是 demo 自己补的 |
| **资源没接** | `resourceOverrides` 是空的。data: 页面无所谓,真实站点的 CSS/图片在回放时会去打原站 —— **要离线回放就得把资源一起存下来** |
| **格式在变** | 同一个 `version: 8`,1.62.1 发的字段叫 `sha1`,main 分支的类型定义已改叫 `file`。这里两个都写。**这就是那条「内部格式,自己写就要跟版本」的风险,现场遇到了** |
| **`<base>` 不能是 data:** | 注入 `<base href>` 时要判协议,否则浏览器报 `'data' URLs may not be used as base URLs` |

## 文件

| | |
| --- | --- |
| `snapshot.js` | DOM → `NodeSnapshot` 嵌套数组。只发全量,不做 `[[n,m]]` 增量引用 —— 增量是带宽优化,写盘没这个压力 |
| `to_trace.py` | 拼 `trace.trace` 事件流 + 打包 |
| `demo.py` | 端到端跑一遍 |
