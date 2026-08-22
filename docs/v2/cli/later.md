# cli · 还没碰的

**每一条都写清楚缺的是后端的什么** —— 不写"以后再说",那等于没记。

## 1. 会话状态:cookies / storage / state

agent-browser:`cookies [set|clear]`、`storage local|session`、
`state save|load|list|clear`、`--restore`。

**我们一条都没有。** 后端缺的是:

- `Network.getCookies` / `setCookies`、`DOMStorage` 域 —— 都是现成的 CDP
- **一个"把这个 session 的登录态存下来/装回去"的概念**

> **这一条对 agent 很关键**:每次都重新登录一遍,又慢又容易触发风控。
> agent-browser 的 `--restore` 甚至能在恢复后**校验**
> (`--restore-check-url` / `--restore-check-text`)—— 因为恢复的登录态
> 可能已经失效,而"以为登录了其实没有"是最难查的一类错。
>
> 形态上它对应 tmux 的什么?**没有对应** —— tmux 的 pane 里跑的是进程,
> 没有"把状态存盘再装回来"这回事。所以这一条是**浏览器特有的**,
> 得按体感那条来想:人会怎么理解"保存登录状态"。

## 2. 环境模拟:set viewport / device / geo / offline / media / headers

后端有一部分:
- **视口**:`Emulation.setDeviceMetricsOverride` 在用(`resize` 那条上行消息)
- **凭证**:HTTP 基本认证有(`browser_ui.py` 的 auth)
- **其余全没有**:设备、地理位置、离线、深浅色、自定义头

🔲 **待讨论:`set media dark|light`。** 这条最常用 ——
现在测深色模式只能改系统设置。CDP 一条 `Emulation.setEmulatedMedia` 就够。

## 3. 比对:diff snapshot / diff screenshot / diff url

agent-browser 用它做视觉回归。**我们没有,而且暂时不该有** ——
这是"前端测试工具"的活,不是"浏览器的 tmux"的活。
判据还是那句:**tmux 会做这个吗?**

## 4. 剪贴板

`clipboard read|write|copy|paste`。后端没有。
CDP 里没有直接的剪贴板 API,要靠 `Input.dispatchKeyEvent` 发 Ctrl+C/V
加上页面里读 `navigator.clipboard` —— **而那需要权限**,
而权限那一套我们有([browser_ui.py](../../../webmuxd/browser_ui.py))。
所以这条**做得了**,只是没人要过。

## 5. 集成:mcp / chat / plugin / skills

- **`mcp`** —— 把 CLI 那张表变成 MCP 工具。🔲 值得,而且**便宜**:
  我们的动词表本来就是封闭的([i §2](../works/i-agent-surface.md#2-动词表)),
  一张表映一张表
- **`chat`** —— 自然语言驱动。❌ **不做**:
  "webmuxd 不产生思考,它只提供手和眼"([v2/sdk §3](../sdk/README.md))
- **`plugin`** —— 进程外扩展。🔲 没有需求之前不做
- **`skills`** —— 内置的操作说明书。🔲 有意思,但先得有稳定的动词表

## 6. 引擎与提供方:--engine / --provider / lightpanda / iOS

agent-browser 支持换引擎和跑 iOS 模拟器。

**我们的 runtime 只有两种**:`process`(本机起一个)和 `remote`(你给一个 CDP 端点)
([h](../works/h-runtime.md))。而 `remote` 已经把这扇门开着了 ——
对面是什么、跑在哪台机器上,不归我们管。**这就是我们对"换引擎"的回答。**

## 7. 安全:--allowed-domains / --action-policy / --confirm-actions

agent-browser 有一整套:域名白名单、动作策略、执行前确认、
把页面输出包在边界标记里(让 LLM 分得清工具输出和不可信内容)。

**我们有的是另一半**:输入收口在
[`input.py`](../../../webmuxd/input.py)(观看者能表达的意图只有 `Input` 域那几条)、
只读 token、特权 URL 拦截、光标值白名单。

🔲 **待讨论:域名白名单。** 这一条最实在 ——
"这个 agent 只许访问这几个站"是能写进部署配置的东西,
而我们今天只拦 `chrome://` 那类。
