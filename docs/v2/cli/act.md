# cli · 操作

**这一层照 agent-browser 的词汇。** 同一件事就用同一个词、同样的参数位置 ——
在两个工具之间来回的人不该重学。

```bash
webmuxd click  -t demo "提交订单"      [--role R] [--name N] [--css SEL] [--at X,Y] [--nth N]
webmuxd type   -t demo "手机号" "138…" [--label L] [--css SEL] [--at X,Y] …
webmuxd key    -t demo Enter
webmuxd scroll -t demo --dy 600
webmuxd send   -t demo '[{"type":"…"}]'
```

## 1. 定位:按人看得见的字

```bash
webmuxd click -t demo "提交订单"                    # 可见文字,最常用
webmuxd click -t demo --role button --name 登录      # 消歧
webmuxd type  -t demo --label 手机号 13800000000     # 表单标签找输入框
webmuxd click -t demo --css "#pay"                  # 逃生舱
webmuxd click -t demo --at 890,632                  # 最后手段
```

**多于一个就报 `not_found` 并列出全部候选,绝不随便挑一个**
([i §2②](../works/i-agent-surface.md#2-动词表))。重试拿候选里的
`role` + `name` —— 那是跨快照仍然成立的说法。

### 和 agent-browser 的定位对照

| agent-browser | 我们 |
| --- | --- |
| `click <sel>`(CSS) | `click --css <sel>` ⚠️ **CSS 在我们这儿是逃生舱,不是默认** |
| `find text <t> click` | `click "<t>"` ✅ 我们把它做成默认 |
| `find role <r> click` | `click --role <r> --name <n>` ✅ |
| `find label <l> type <v>` | `type --label <l> <v>` ✅ |
| `find nth <n> <sel> click` | `click --css <sel> --nth <n>` ✅ |
| `@e1` 这种 **ref** | 🔲 **没有** —— 见 [read.md](read.md) 里 `snapshot` 那一节 |

> **为什么 CSS 不是默认。** agent-browser 面向的是"agent 先 snapshot 拿 ref、
> 或者开发者自己写选择器"。我们面向的是"照着人看到的东西操作" ——
> 选择器一改版就失效,而"登录"两个字不会。
> **这是体感那条(对齐普通浏览器)在定位上的样子。**

## 2. CLI 暴露的动词比后端少

后端[动词表](../works/i-agent-surface.md#2-动词表)有这些,`send` 都能用:

```
goto back forward reload stop
click hover scroll
type clear key select check upload
extract wait_for
js
```

而 CLI 只给了 `click` `type` `key` `scroll`。剩下的要写 `send` 的 JSON:

```bash
webmuxd send -t demo '[{"type":"select","role":"combobox","value":"b"}]'
```

⚠️ **待做(不是待讨论 —— 后端已经有了,只差把它摆成 flag):**

| 后端动词 | 该长成 | 对应 agent-browser |
| --- | --- | --- |
| `hover` | `webmuxd hover -t demo "…"` | `hover <sel>` |
| `clear` | `webmuxd clear -t demo --label 手机号` | (`fill` 的一半) |
| `select` | `webmuxd select -t demo --role combobox b` | `select <sel> <val>` |
| `check` | `webmuxd check -t demo "同意条款"` | `check` / `uncheck` |
| `upload` | `webmuxd upload -t demo "选择文件" ./a.png` | `upload <sel> <files>` |
| `extract` | `webmuxd extract -t demo --css ".item" --mode table` | `get text/html` |

`fill`(清空再填)= `clear` + `type`,agent-browser 把它做成一个命令 ——
**值得抄**,因为"填表单"十次有九次要的是这个。

🔲 **待讨论:低层鼠标。** agent-browser 有 `mouse move/down/up/wheel`。
我们的观看端那条通道**本来就是这个**(`{"type":"mouse","event":"move",…}`),
但 CLI 没有出口。给不给,取决于"CLI 要不要能模拟人的连续动作" ——
今天 `--at X,Y` 只能点一下,拖不了。

🔲 **待讨论:`drag` / `dblclick` / `keydown` / `keyup`。**
`drag` 后端也没有,[动词表那一篇](../works/i-agent-surface.md#21-还缺的动词)
已经把它列成缺的了。

## 3. `send` 是逃生舱,也是全集

```bash
webmuxd send -t demo '[{"type":"click","text":"登录"},
                       {"type":"type","label":"手机号","text":"138…"},
                       {"type":"key","key":"Enter"}]'
```

**一批动作按顺序跑,遇错即停。** 这是 CLI 唯一能表达"一串"的地方 ——
对应 agent-browser 的 `batch`。

`js` 也在这儿:**它是逃生舱,日志里标黄** —— 它绕过了上面所有的语义,
回看时看不出到底干了什么。

## 4. `dialog` —— 页面弹了个 `confirm`

```bash
webmuxd dialog -t demo                 # 接受
webmuxd dialog -t demo --text "张三"    # prompt 的回填
webmuxd dialog -t demo --dismiss       # 取消
```

对上 agent-browser 的 `dialog accept|dismiss`。

**我们不自动回应。** 该点确定还是取消是调用方的判断 ——
弹窗挂着的时候,那个 tab 上的动作**一律回 `busy`(退出码 6)**,
错误里带着弹窗的 `kind` 和文字([sessions.py](../../../webmuxd/sessions.py))。

> 为什么要挡而不是排队:`alert` / `confirm` / `beforeunload` 一弹出来,
> 那个 tab 上后续的 CDP 调用会**挂着不返回** —— 不是慢,是死等。
> 与其让调用方等到超时,不如立刻告诉它"被弹窗挡住了,这是弹窗内容"。

弹窗出现会进[行为流](debug.md)(`kind: dialog`),回看时看得见
"到这儿弹了个东西"。
