# 03 · 操作日志

**回看它干了什么。** 这就是 tmux 的 scrollback,只不过记的不是终端输出,
是"谁在哪个 tab 上做了什么、结果如何"。

> 早先这篇还包含一个**查看页面**(左边 VNC、右边日志面板)。**去掉了** ——
> 容器只暴露两个口:干净的 KasmVNC,和 webmuxd 的 API。
> 画面怎么摆、日志怎么显示、tab 条长什么样,**上层自己组织**
> ([04](04-chrome-ui-externalization.md) 讲怎么裁 Chrome 自带的 UI)。
> 我们自己带一个页面是过渡设计:它既不是产品,又让人误以为那是标准形态。

## 1. 存哪

### 1.1 一个文件

```
/data/
├── log.jsonl        ← 当前这一刀
├── log.1.jsonl      ← 上一刀
└── shots/0042.webp  ← 按 seq 命名
```

**不分 tab、不分类型,全在一个 jsonl 里。** 要哪部分就筛哪部分:

```bash
grep '"tab":"t_7"'    /data/log.jsonl     # 某个 tab 干过什么
grep '"kind":"tab"'   /data/log.jsonl     # tab 的生老病死
grep '"ok":false'     /data/log.jsonl     # 失败的
```

**一行一条 JSON,就是为了这个。** 曾经想过按 tab 分文件(读一个 tab = 读一个文件),
但在一万行的量级上筛一遍的成本可以忽略,而分文件要额外维护一套目录生命周期 ——
不值。tab 数本来也有上限(§7)。

**`seq` 全局单调**,和事件流共用一个计数器,所以两边对得齐。

### 1.2 三类记录

每条都有 `kind`,只有三种:

| `kind` | 记什么 |
| --- | --- |
| `action` | **有人做了一件事** —— 点击、输入、导航、观测 |
| `tab` | **tab 的生和死** —— 建了、关了、被挤掉了,带 `reason` 和 `final_url` |
| `session` | **整个 session 的事** —— Chrome 崩了重拉、`reset` |

**没有第四类。** 页面自己的变化(标题变了、loading 变了)不进日志 ——
没有人"做"它们,它们只是事件(§5)。

```jsonc
{ "seq": 118, "kind": "tab", "event": "opened", "tab": "t_7",
  "url": "https://help.example.com", "reason": "link_target_blank", "user": "human" }
{ "seq": 402, "kind": "tab", "event": "closed", "tab": "t_7",
  "final_url": "...", "reason": "evicted" }
{ "seq": 511, "kind": "session", "event": "chrome_restarted", "restarts": 1 }
```

问"这个 tab 什么时候建的、谁建的、活了多久、关的时候停在哪",
`grep '"kind":"tab"'` 就够了。

### 1.3 每条动作记录

```jsonc
// /data/log.jsonl 里的一条
{ "seq": 42, "at": "14:22:03", "kind": "action", "tab": "t_3",
  "action": "click", "target": { "text": "登录" },
  "hit": { "role": "button", "name": "登录", "bbox": [820,612,140,40] },
  "ok": true, "ms": 412,
  "after": { "url": "/login", "changed": "出现『请输入手机号』" },
  "shot": "shots/0042.webp",          // 按 seq 命名
  "user": "claudecode", "note": null }
```

关键设计:

- **`after.changed` 是一句人话** —— 「出现『订单已提交』」比「DOM 变了 34 个节点」有用一百倍。
  由简单启发式生成:新出现的最大文本块 / 消失的表单 / 新的 `role=alert`。
- **每个动作存一张动作后的截图**(webp,~100KB)。点日志任一行 → 左边画面暂时切成那一刻的截图,
  并把 `hit.bbox` 画出来。再点一下回到实时画面。这是"回放",但只是切图片,没有播放器工程。
- **人的操作也进日志**,标 👤。sessiond 被动监听页面变化,记下导航和表单提交。
  这样日志是完整的操作路径,不是"只有 API 干过的事"。
- **失败标红,带候选元素**。`js` 和坐标点击标黄(看不出干了什么)。
- **密码自动打码**:`input[type=password]` 里输的内容在日志和截图里都是 `••••`。

## 2. 加一行"它在想什么"

日志的价值在于能回答"它为什么点错了"。光有动作还不够 —— 加个可选字段就行:

```python
tab.note("购物车里已有一张票,现在需要确认支付") # 下一个动作会带上这句
tab.click(obs[8])
```

日志里就变成:

```
14:22:06 💭 购物车里已有一张票,现在需要确认支付
         click [8] "取消订单"          ← 一眼看出它认错了元素
         → /cancel  出现『订单已取消』
```

**这一行是"操作路径可见"的核心。** 不需要 Run/Step 建模、不需要数据库 —— 就是日志里多一行。
不调 `note()` 也能用,只是回看时少了最有用的一列。

## 3. 和事件流是两回事

容器里还有一条 WS 在推变化通知([06 §5](06-tab-sync.md#5-推给客户端)),
两个东西容易混,钉一下:

| | 事件流 | 日志 |
| --- | --- | --- |
| 干嘛的 | 让上层的 UI **不用轮询** | 让人**能回看** |
| 活多久 | 内存里 1000 条,进程一重启就没 | 落盘,按 `history-limit` 截断 |
| 丢不丢 | 丢,丢了发 `gap` | 不丢 |

一次 `click` 出 6 条事件、1 条日志 —— 事件记的是**变化**(标题变了、loading 变了),
日志记的是**有人做了一件事**。`log.appended` 是接缝:它是"刚写了一条日志"这个通知本身。

**共用一个 `seq`**,所以拿日志里某条的 seq 能在事件流里找到它前后发生了什么。

写脚本的人两个都不用碰:lib 替他订了事件、日志直接 `sess.log()` 拉。

## 4. 导出

```bash
curl localhost:7900/api/log > log.jsonl                    # 全部,按 seq 归并
curl 'localhost:7900/api/log?tab=t_7' > t_7.jsonl          # 一个 tab
curl 'localhost:7900/api/log?kind=tab' > lifecycle.jsonl   # 只要 tab 的生老病死
curl localhost:7900/api/log/bundle > bundle.zip            # 日志 + 截图 + 离线 HTML
curl 'localhost:7900/api/log/bundle?tab=t_7' > t_7.zip     # 打包一个 tab 的目录
```

`bundle.zip` 解开双击就能看,不依赖容器还活着。用来把"它当时干了什么"发给别人。

## 5. 保留

两层,都不是归档系统:

| | 限额 | 超了怎么办 |
| --- | --- | --- |
| **同时开着的 tab** | `WEBMUXD_TAB_MAX` 个(默认 10) | **挤掉最不活跃的那个**(LRU) |
| **日志条数** | `WEBMUXD_LOG_LIMIT` 条(默认 5000) | **切一刀**:改名 `log.1.jsonl`,开新的;只留上一刀 |

所以在线记录**永远在 5000~10000 条之间**,按每条 ~100KB 截图算,磁盘约 1GB 封顶。
切掉那一刀时,它那批 seq 的截图一起删。

**两层是同一个形状**:有界、老的先走、不做归档 —— 就是 `history-limit` 那套。

### 5.1 为什么 tab 也要有上限

内存那边很直接:每个活着的 tab 是一个渲染进程。而**最容易失控的恰恰不是人**,
是页面自己 `window.open` 一串(而我们还把 popup 全转成了 tab,[07](07-popup-windows.md))、
或者一个 agent 循环里每轮开一个新 tab 忘了关。

LRU 而不是 FIFO,是因为**先开的不等于最没用的** —— 一个开着不动的登录态 tab
可能正是你要留的那个。按"最后一次被激活或被操作"排,规矩是:

- **当前激活的永远不挤**(人正看着的东西不能在眼前消失)
- **正在跑动作的不挤**(会让那个动作变成一半)
- **先建后挤**(新建的不会被自己挤掉)

**这条会咬人**:脚本手里的句柄可能在它脚下死掉。所以事件、日志、异常三处
**都标 `reason: "evicted"`**,不会让你以为是自己关的
([api/tabs.md §3](../api/tabs.md#3-写))。被挤掉的 tab 的记录还在日志里,
`final_url` 也在,想恢复自己重开 —— 直到那一刀切走。

**这是 tmux 的 `history-limit`,不是归档。** 真要长期留就自己定时拉 `/api/log`,
或者 `bundle` 下来。
