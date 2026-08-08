# 03 · 查看页面与操作日志

打开 `http://localhost:7900` 看到的东西。一个纯静态页面,不需要构建系统,不需要后端渲染。

## 1. 布局

```
┌──────────────────────────────────────────┬──────────────────────────┐
│                                          │  操作日志          [清空] │
│                                          ├──────────────────────────┤
│                                          │ 14:22:01 goto            │
│        远端 Chrome 的实时画面            │   shop.example.com       │
│        (KasmVNC,可直接用鼠标键盘操作)  │ 14:22:03 click "登录"    │
│                                          │   → /login               │
│                                          │ 14:22:04 type "手机号"   │
│                                          │   138••••0000            │
│                                          │ 14:22:06 click "提交"    │
│                                          │   ✗ 找不到               │
│                                          │   候选: 提交订单 / 确认  │
│                                          │ 14:22:09 👤 人点了 (612,│
│                                          │   340)                   │
│                                          ├──────────────────────────┤
│                                          │ ⏸ 暂停滚动  🔍 只看失败  │
└──────────────────────────────────────────┴──────────────────────────┘
```

左边是画面(attach),右边是 scrollback。就这两块。

## 2. 左边:画面

直接嵌 KasmVNC 的客户端([01 §1](01-container.md#1-一张图))。**不做二次封装。**

- 可以直接用鼠标键盘操作里面的 Chrome —— 遇到验证码、二次验证、奇怪弹窗,自己上手点掉
- 不需要"接管模式"切换。人点人的,API 跑 API 的,像 tmux 多个 client 同时 attach
- 关掉网页,容器照跑

## 3. 右边:操作日志(这就是"操作路径能看到")

### 3.1 一个 tab 一个文件

```
/data/
├── session.jsonl              ← 目录:tab 什么时候建的、什么时候销毁的
└── tabs/
    ├── t_3/
    │   ├── log.jsonl          ← 这个 tab 的操作记录
    │   └── shots/0042.webp
    └── t_7/
        ├── log.jsonl
        └── shots/
```

**为什么按 tab 分,而不是一个大文件:**

- **tmux 的 `history-limit` 是每个 pane 的**,不是每个 session 的。tab 就是我们的 pane,
  按 tab 分才是忠实映射。
- **一个话痨 tab 不该把别的 tab 的历史挤掉。** 全局一个 500 条的环,
  一个刷新循环跑十分钟就把整个 session 的记录冲干净了。
- `GET /api/log?tab=t_7` 从"过滤"变成"读一个文件";
  `bundle?tab=t_7` 从"筛一遍"变成"打包一个目录"。
- tab 关掉之后它的目录**还在**,所以"那个已经关掉的 tab 当时干了什么"查得到。

**`seq` 仍然全局单调。** 每条记录都带,所以跨文件按 seq 归并就能还原全序 ——
分文件是存储布局,不是把时间线切开。事件流用的是同一个计数器。

### 3.2 `session.jsonl` —— 这个 session 的目录

**tab 的生老病死落在这儿**,不是只有一个转瞬即逝的 WS 事件:

```jsonc
{ "seq": 118, "at": "...", "kind": "tab", "event": "opened",
  "tab": "t_7", "url": "https://help.example.com", "title": "帮助中心",
  "reason": "link_target_blank", "opener": "t_3", "user": "human" }

{ "seq": 402, "at": "...", "kind": "tab", "event": "closed",
  "tab": "t_7", "final_url": "https://help.example.com/ticket/9", "user": "api" }

{ "seq": 511, "at": "...", "kind": "session", "event": "chrome_restarted", "restarts": 1 }
```

问"这个 tab 什么时候建的、谁建的、活了多久、关的时候停在哪",**读这一个文件就够了**。

它**不做环形截断** —— 每个 tab 才两行,开关十万个 tab 也就十来 MB。
目录比细节活得久:tab 的 `log.jsonl` 可能已经被清掉了,但"它存在过"这件事一直在。

### 3.3 每条动作记录

```jsonc
// /data/tabs/t_3/log.jsonl 里的一条
{ "seq": 42, "at": "14:22:03", "kind": "action", "tab": "t_3",
  "action": "click", "target": { "text": "登录" },
  "hit": { "role": "button", "name": "登录", "bbox": [820,612,140,40] },
  "ok": true, "ms": 412,
  "after": { "url": "/login", "changed": "出现『请输入手机号』" },
  "shot": "shots/0042.webp",          // 相对本 tab 目录
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

## 4. 给 Agent 加一行"它在想什么"

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

## 5. 事件流

页面靠 WS 实时更新;你的程序也能订阅:

```python
for e in web.watch():
    print(e.action, e.ok)
```

```
GET /api/events            (WS)
{ "seq": 42, "action": "click", "text": "登录", "ok": true, "ms": 412 }
```

断线重连带 `?after=42` 续上。

## 6. 导出

```bash
curl localhost:7900/api/log > log.jsonl                    # 全部,按 seq 归并
curl 'localhost:7900/api/log?tab=t_7' > t_7.jsonl          # 一个 tab,直接读文件
curl 'localhost:7900/api/log?kind=tab' > lifecycle.jsonl   # 只要 tab 的生老病死
curl localhost:7900/api/log/bundle > bundle.zip            # 日志 + 截图 + 离线 HTML
curl 'localhost:7900/api/log/bundle?tab=t_7' > t_7.zip     # 打包一个 tab 的目录
```

`bundle.zip` 解开双击就能看,不依赖容器还活着。用来把"它当时干了什么"发给别人。

## 7. 保留

两层,都不是归档系统:

| | 限额 | 超了怎么办 |
| --- | --- | --- |
| 每个 tab 的 `log.jsonl` | `WEBMUXD_LOG_LIMIT` 条(默认 500) | 环形截断,老的连截图一起删 |
| 已关闭 tab 的目录 | `WEBMUXD_TAB_KEEP` 个(默认 50) | 整个目录删掉 |
| `session.jsonl` | 不截断 | —— |

**`WEBMUXD_LOG_LIMIT` 现在是每 tab 的**,不是全局的 —— 这是 §3.1 那次拆分的直接后果,
也正是 tmux `history-limit` 的语义。磁盘上限因此变成
`500 条 × ~100KB × (活着的 tab + 50)`,几个 GB 的量级,**开着的 tab 越多占得越多**。

删掉一个已关闭 tab 的目录之后,`session.jsonl` 里它那两行**还在** ——
你仍然知道它存在过、什么时候关的、关的时候停在哪,只是逐步的动作没了。

**这是 tmux 的 `history-limit`,不是归档。** 真要长期留就自己定时拉 `/api/log`,
或者 `bundle` 下来。
