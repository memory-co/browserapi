# 03 · 输入翻译

**一句话**:客户端的鼠标键盘被归一化成 JSON 发上来,服务端翻译成 CDP 的 `Input.*` 打回远端。
**这层翻译就是整个安全模型的收口** —— 观看者能对远端做的事,全部被限制在 `Input` 域那几个命令里。

## 1. 收口在哪

```
浏览器里的 DOM 事件 ──归一化──> webmuxd ──> CDP Input.dispatchMouseEvent
                                              CDP Input.dispatchKeyEvent
                                              CDP Input.insertText
                                              CDP Input.dispatchWheelEvent
                                        └──> 就这些,没有别的
```

观看者**拿不到 DOM,执行不了脚本,发不出任意 CDP 命令**。他能表达的全部意图就是
"在某个坐标点一下""按某个键" —— 和坐在真实浏览器前的人能做的事完全等价,不多不少。

这和 VNC 那条路的安全边界其实是同一条(RFB 也只能送鼠标键盘),
**区别在于 v2 里这条边界是我们自己实现的,所以它可以带条件** —— 见 §5 和 [04 §3](04-one-port.md#3-读和写是两个-token)。

## 2. 键盘:带 `text` 的 `keyDown`,不是 `insertText`

demo 实测过的一条,直接抄结论:

| | 字符能进输入框 | 页面收到真实 `keydown` |
| --- | --- | --- |
| `Input.insertText` | ✅ | ❌ |
| `Input.dispatchKeyEvent(type=keyDown, text=…)` | ✅ | ✅ |

**必须用后者。** 监听按键的页面 —— 快捷键、搜索框联想、游戏、编辑器 —— 只有收到真实
`keydown` 才工作。demo 的自测里"远端页面收到真实 keydown 事件"就是这一项。

`insertText` 不是没用,它是 **IME 提交**和**粘贴**的正确工具(§3、§4),
因为那两种场景本来就不该逐字符伪造按键。

一次按键要发的是完整三元组:`keyDown` → (`char`) → `keyUp`,
带齐 `key` / `code` / `windowsVirtualKeyCode` / `modifiers`。少一样,
`e.key` 判断和 `preventDefault` 的页面就会行为异常。

## 3. IME:输入法这条路反而更短

VNC 传中文是老大难:要么在服务端装一整套输入法(候选词框还得作为像素传回来,
延迟直接叠加在打字上),要么让客户端组字、服务端按键,两边错位。

v2 里这个问题**从根上不存在**:

```
用户在自己的浏览器里打字 → 本地 IME 组字(候选词框是本地 UI,零延迟)
                          → compositionend 拿到最终文本 "提交订单"
                          → Input.insertText("提交订单")   一次,不是四次按键
```

组字过程**完全不出本地**。客户端监听 `compositionstart` / `compositionend`,
组字期间**不发任何按键事件**(否则远端会收到一串乱码般的字母),
`compositionend` 时一条 `insertText` 送最终文本。

这是 v2 相对 v1 的净胜,不是打平。代价是组字期间远端页面看不到"正在输入"的中间态 ——
对搜索联想那类页面有轻微影响,可接受。

## 4. 剪贴板

| 方向 | 做法 |
| --- | --- |
| 本地 → 远端 | 客户端 `paste` 事件拿 `clipboardData` → `Input.insertText` |
| 远端 → 本地 | 客户端按 Ctrl+C 时,服务端 `Runtime.evaluate` 读 `document.getSelection().toString()`,回给客户端写进本地剪贴板 |

反向那条要用户手势才能写本地剪贴板(浏览器限制),所以它挂在客户端的 `copy` 事件里做。

**只读观看者两个方向都禁**:粘贴属于写,复制属于把远端内容**带出隔离边界** ——
后者是不是该禁取决于场景,v2 的选择是**跟随写权限**(只读就是只能看,不能带走),
需要放开时那是另一个 token 的事,不是默认。

## 5. 光标同步

远端页面里光标是什么形状,本地就跟着变(链接上是手型、文字上是 I 型、
可拖拽的地方是 grab)。没有这个,画面上一切都是箭头,**人会分不清哪里能点**。

**CDP 里没有「光标变了」这种事件** —— 光标是纯渲染层的东西,screencast 的帧里也不含光标。
所以只能往页面注入探针(demo 的 `lib/cursor.js`):

1. `Runtime.addBinding` 在页面里造一个回调函数,页面调它服务端就收到 `Runtime.bindingCalled`
2. `Page.addScriptToEvaluateOnNewDocument` 注入探针,保证每次导航后都在
3. 探针监听 `pointermove` / `pointerdown` / `scroll`,用 rAF 节流,
   `elementFromPoint` 找命中元素,读 `getComputedStyle().cursor`,**值变了才上报**

所以它基本不占带宽。

### 两个坑,都得照抄

**`cursor: auto` 要靠命中测试。** `auto` 的语义是"文字上显示 I 型,其它地方显示箭头",
光读计算样式区分不出来 —— 两种情况读出来都是 `auto`。探针用 `caretRangeFromPoint`
拿到文字节点,再逐个比对它的 `getClientRects()` 确认指针确实落在字的矩形内。
`caretRangeFromPoint` 会"吸附"到最近的文字,**不加这层校验会导致空白处也报 I 型**。

**返回值必须过白名单。** 这个值会被直接写进客户端的 `style.cursor`,而**远端页面是不可信的**。
CSS 的 `cursor` 支持 `url(...)` 自定义光标 —— 原样透传等于让被隔离的页面指使
客户端去拉任意 URL,隔离性当场破掉。只放行 CSS 规范里的关键字,其余一律降级成 `default`。

> 顺带:BrowserBox 并没有做这个功能。它的 `showMouse.js` 干的是另一件事 ——
> 在远端页面里画一个假光标圆点给协同浏览的其他人看,属于"在场感",不是本地光标同步。

## 6. 注入的探针是不是破坏了"同一个浏览器"

值得说清楚,因为 webmuxd 开篇那句承诺是"你自己拿 DevTools 连上去,看到的和我们看到的一样"。

光标探针是 `addScriptToEvaluateOnNewDocument` 注入的,它**确实改变了页面环境**:
多了一个 `window` 上的 binding。这一条要如实写进文档,不能装作没有。

三条自律:

- **只注入这一个探针**,不为了实现别的功能继续加
- 名字带明显前缀,`observe()` 的元素表里**过滤掉它自己**
- 页面能看见它 —— 这是 CDP binding 的固有性质,不假装能隐藏。
  反爬场景对此敏感,是 v2 的已知特征,不是 bug

## 7. ↔ 别处

| | |
| --- | --- |
| 谁有权发输入 | [04 §3](04-one-port.md#3-读和写是两个-token) |
| 输入事件走哪条连接 | [02 §1](02-frame-protocol.md#1-为什么是二进制头不是-json) |
| 程序化操作(`click("提交订单")`)走哪条路 | 不走这里,走 `core/act` —— [08 §2](08-migration.md#2-一个字没动的东西) |
