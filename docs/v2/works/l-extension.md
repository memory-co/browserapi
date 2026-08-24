# l · sidecar 变成 Chrome 扩展?

**一句话**:实测下来 —— **sidecar 那四样,扩展一样不缺,而且样样更好**。
唯一真正换不掉的是 `remote`(那条路上装不了扩展)。
所以问题从来不是"可不可行",是**"要不要多一条腿"**。

> 设计评估。下面每个"实测"都是在本机 Chromium 152.0.7977.42 上跑出来的,
> 脚本形状见 §7。

## 1. 实测:四条,全过

| 问什么 | 结果 |
| --- | --- |
| `--headless=new` 装不装得上 MV3 扩展 | **装得上**。`/json` 里出现 `service_worker chrome-extension://…/sw.js` |
| 有头 `--kiosk`(VNC 那条腿)呢 | **也装得上**。Xvfb + `--kiosk` 下同样出现 |
| CDP 发的 `Target.activateTarget`,扩展听得到吗 | **听得到**。每一次都有一条 `chrome.tabs.onActivated` |
| rrweb 放**隔离世界**录得动吗 | **录得动**,而且页面主世界**完全干净** |

第三条和第四条是这篇的全部价值,分别在 §2 和 §4。

## 2. `chrome.tabs.onActivated` 比我们那个探针准

### 2.1 实测:一条事件就说清了"前台开还是后台开"

同一个 `target=_blank` 链接,两种点法,扩展那边收到的:

```
普通左键   created {tabId, opener, active: true}   +  activated {tabId, windowId}
Ctrl+左键  created {tabId, opener, active: false}     ← 没有 activated
```

**`active` 直接在 `onCreated` 里**,而且后台开的那次**根本不发 `onActivated`**。

对比今天那条路([f §3](f-tabs.md)):

| | 今天(页面探针) | 扩展 |
| --- | --- | --- |
| 怎么知道前台换了 | 页面报 `visibilitychange` | `chrome.tabs.onActivated` |
| 新 tab 说得出话吗 | **说不出** —— 探针是 `executor_for()` 那一刻才注的,页面开的 tab 在被人碰之前 `window.__wm_side` 是 `undefined` | **说得出**,`onCreated` 就带 `active` |
| 因此要 | 每个 tab **一进表就注探针**、两个方向都报、等确认、等不到再问一次 | 收事件 |
| `activate` 要不要等回流 | **要**,而且要能超时报 `tab_not_front` | 事件到了就是到了 |
| 能删掉的 | | `_prepare_tab` `_confirm_front` `_ask_front` `_FRONT_WAIT`、`foreground.ts`、以及"一进表就装探针"那条 |

**它还顺带给了三样今天要自己算的**:`openerTabId`(我们今天从 `openerId` 推
`reason`)、`index`、`windowId`。

### 2.2 而且 `TabInfo` 本来就是照 `chrome.tabs` 对齐的

[f §2.1](f-tabs.md#21-那张表的形状) 那句"字段和 `chrome.tabs` 对齐,
便于直接映射"—— 扩展这条路等于**让那句话从"照着抄"变成"就是它"**。

## 3. 但 `chrome.windows.onFocusChanged` 不是我们要的那个

**实测:全程一次都没触发。**

它回答的是"**哪个窗口**拿到了操作系统的焦点",而我们:

- headless 那条:没有窗口管理器
- VNC 那条:`--kiosk`,**只有一个窗口**,而且它永远是焦点

要的是 `chrome.tabs.onActivated`(哪个 **tab** 到了前台),不是它。
两者名字像,管的是不同层的东西 —— 这一条值得写下来,因为它是最容易选错的一个。

## 4. rrweb:隔离世界才是真正的收获

**实测**:把 rrweb 作为 `run_at: document_start` 的内容脚本(默认就是隔离世界),
在 `/ticker` 那一页上录 5 秒:

```
录到 28 条:{"0":1, "1":1, "2":1, "3":24, "4":1}
              ↑DomContentLoaded  ↑FullSnapshot  ↑24 条增量  ↑Meta
```

同时问页面**主世界**:

```json
{"rrweb":"undefined", "rec":"undefined", "define":"undefined",
 "keys":["onerror","onmessageerror","reportError","onpointerrawupdate"]}
```

**页面上一个字节都没多。**

这一下消掉了三样今天实打实的负担:

| 今天的坑 | 隔离世界之后 |
| --- | --- |
| **UMD 被页面的 AMD 加载器劫走** —— `rrweb.py` 里那个 `_umd_shield()` 要在注入前后把 `define`/`module`/`exports` 藏起来 | 不存在。页面的 `define` 我们根本碰不到 |
| **"探针改变了页面环境"是一条明说的代价**([b §6](b-input.md)) | 对反自动化检测敏感的场景,这条代价**没了** |
| 注入时机要靠 `waitForDebuggerOnStart` 把新 target 停住,注完再放行 | `document_start` 是浏览器给的保证,不用我们停页面 |

sidecar 里另外两样也能搬进隔离世界:**光标**(`elementFromPoint` +
`getComputedStyle`,内容脚本和页面共享 DOM)和**人在动没在动**
(捕获阶段的 `pointerdown`/`keydown`,内容脚本收得到)。

## 5. 换不掉的那些

### 5.1 ~~`open-shim` 必须留在主世界~~ —— 写错了,而且反了

> **这一节原来的结论是错的,留着改正。**
> 原文说"隔离世界改不了页面的 `window.open`,所以四样里三样能搬,第四样搬不了"。
> 前半句对,后半句**不成立** —— 它把"隔离世界做不到"当成了"扩展做不到"。
> 扩展的内容脚本可以指定 `world: "MAIN"`(Chrome 111+),照样改得了。

**而且扩展根本不用改它。** popup 转 tab 有一条不碰页面的路:

```js
chrome.tabs.onCreated.addListener(async (tab) => {
  if (tab.windowId === mainWin) return;
  await chrome.tabs.move(tab.id, { windowId: mainWin, index: -1 });
});
```

实测(扩展**没有内容脚本、没有 `host_permissions`**,页面上一个字节都没注):

| 页面调的 | 今天的 shim | 这个扩展 |
| --- | --- | --- |
| `width=400,height=300,left=10` | tab,返回 `Window` | **tab**,返回 `Window` |
| `popup=1` | tab | **tab** |
| `noopener,width=400` | tab,返回 `null` | **tab**,返回 `null` |
| **`attributionsrc`** | **POPUP** ⚠ 白名单放它过去了 | **tab** |

三处它比 shim 强,而且都不是小事:

1. **不碰页面。** 没有 `window.open` 补丁、没有伪造 `toString` ——
   [b §6](b-input.md) 那条"探针页面看得见"的代价,这一样上没有了。
2. **不需要白名单,所以没有那个洞。** 今天 `KEEP` 里留着 `attributionsrc`,
   而实测它**照样开出真窗口**(代码注释写的"它们不触发 popup"是错的)。
   扩展这条路**从不解析 features 串**,所以不存在"少列了一个词"这种失败。
3. **语义自动保住。** `noopener` 仍然返回 `null` —— 因为那是 Chromium
   自己算的,我们没插手。shim 要靠一条正则**记得**把它留下。

搬完之后 opener 关系也完好,实测:

```
opener 手里那个句柄 : {closed:false, 能写 document, postMessage 发得出}
被开那一页看到的    : {opener:true, title:"被 opener 改过"}
```

**唯一的真代价**:那个 popup 窗口是**真的被创建了**,然后才被搬走。
无头下看不出来;**有头(VNC)那条腿上它可能闪一下** —— 那是一个真的 X 窗口。
这一条**没在有头下实测过**,要做之前得补。

### 5.2 `remote` 那条路上装不了

`--load-extension` 是**起浏览器时**的参数。`remote` runtime 连的是**别人已经起好的**
浏览器([h](h-runtime.md)),我们加不上。

这是这篇里最要紧的一条,见 §6。

### 5.3 MV3 的 service worker 会休眠

事件会把它唤醒,但**内存里的状态没了**。所以它只能当"转发器":收到事件立刻
发出去,不在里面攒东西。

发到哪儿:实测可以**用 CDP attach 到那个 SW target**,和别处一样走
`Runtime.addBinding` —— 不用给它开第二条连接。(附带效果:attach 着的时候
它不会被回收。)

### 5.4 多一个构建产物和一条打包路

扩展是第三棵要建的树(`_client` / `_sidecar` 之后),而且
`--load-extension` 要一个**目录**,不能是一个文件 —— 得解到磁盘上。

## 6. 真正的问题:它会变成第二条腿

把 §5.2 摊开说:

```
process runtime   →  能装扩展  →  用 chrome.tabs 那套
remote  runtime   →  装不了    →  只能继续用页面探针
```

**两套实现做同一件事** —— 这正是这个项目一路在拆的东西
(`models` 那份账、`active` 那本账、日志渲染那两份)。

两条出路,**必须选一条**:

### ① 扩展是一种 runtime 能力,不是一个实现细节

和"VNC 要有头浏览器"完全同构:

```python
available_in(headed=…, remote=…)     # 今天:能切到哪几种画面
```

变成:**装不上扩展的 session,`dom` 那条腿和"前台跟随"不可用,而且当场说出来**
—— 不静默退回探针。这符合 [h](h-runtime.md) 那条"**不可用就抛,不降级**"。

代价:`remote` 那条路能力变少,而且是**明面上**变少。

### ② 只在扩展装上时用它,装不上就退回探针

代价:**两套实现长期共存**,而且它们的行为差异(比如 Ctrl+左键分不分得清)
会变成"看运气"。**这条我不建议** —— 它就是"静默降级"换了个名字。

> 我倾向 ①。理由不是洁癖:两套实现里那条**不常走的**必然先烂,
> 而且烂了没人知道 —— 这次那个 `active` 事故就是这么来的。

## 7. 怎么验的

```
扩展 = manifest v3 + sw.js(收 chrome.tabs.* 事件)+ rrweb.js + rec.js(内容脚本)
起法 = chrome --load-extension=<dir> --disable-extensions-except=<dir>
       无头:--headless=new        有头:DISPLAY=:91 --kiosk
读法 = CDP attach 到 service_worker target,Runtime.evaluate 读它攒的那个数组
```

四条实测的原始输出记在这一篇的提交信息里。

## 8. 如果要做,从哪一步开始

**不做"全都搬到扩展"。** 按买到的东西排:

| | 买到什么 | 动多少 |
| --- | --- | --- |
| 0 | **popup 转 tab 换成 `chrome.tabs.move`** —— 不碰页面、没有白名单、`attributionsrc` 那个洞自动消失 | 一个只要 `tabs` 权限的扩展,**连内容脚本都不用** |
| 1 | **rrweb 进隔离世界** —— 消掉 `_umd_shield`、消掉"改变页面环境"那条代价 | 只动 `rrweb.py` 的注入那一段 |
| 2 | **前台走 `chrome.tabs.onActivated`** —— 删掉 `_confirm_front` / `_ask_front` / `foreground.ts` / "一进表就装探针" | 动 `tabs.py` `sessions.py` |
| 3 | tab 表整个换成 `chrome.tabs` | **先别做**,见下 |

第 3 步先别做,因为两套 id 会打架:我们要 CDP 的 `targetId` 去 attach、
去 `startScreencast`,而扩展给的是 `chrome.tabs` 的 `tabId` ——
**多一层映射,而映射是会漂的东西**。今天 `t_N ↔ targetId` 已经是一层了,
再加一层要先想清楚谁是主键。

**每一步之前先回答 §6 那个选择。** 没定下来就动手,结果一定是 ②。

## 9. ↔ 别处

| | |
| --- | --- |
| 今天那条前台是怎么做的 | [f §3](f-tabs.md) |
| 页面里那一段今天长什么样 | [b §6.1](b-input.md) · [`webmuxjs/sidecar/`](../../../webmuxjs/sidecar/) |
| DOM 那条腿 | [c §5](c-view.md) |
| runtime 只做一件事 | [h](h-runtime.md) |
