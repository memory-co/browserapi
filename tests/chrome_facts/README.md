# chrome_facts — 我们对 Chromium 的假设,逐条量过

## 这个场景在测什么

这个项目的一半建立在"CDP 会这样表现"之上。这些假设**不能靠读文档**,
所以这里把它们变成会红的断言:

1. **四种开 tab 的方式全都带 `openerId`** —— 包括 `noopener`。
   `noopener` 切断的是页面侧的 `window.opener`,而 `openerId` 是浏览器层的血缘记录。
   `reason` 的判据就建立在这条上。
2. `setDiscoverTargets` 会把**已存在的** target 各补一条 `targetCreated` ——
   接管一个跑着的浏览器不会漏。
3. `Runtime.callFunctionOn` 绑的是 `this`(箭头函数会拿到 undefined)。

## 不在这测什么

- 我们自己的 tab 表怎么维护 —— 在 [`tab_identity/`](../tab_identity/)。

换 Chromium 大版本时,**先跑这个场景**。它红了说明假设变了,而不是我们写错了。
