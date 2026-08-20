# DOM 那条画面:注入登记成功,脚本从不执行

**状态**:未解决,挂起。DOM 模式因此不可用 —— JPG / VNC 不受影响。
**日期**:2026-08-20

## 症状

`--transport dom` 起的 session,页面里探不到记录器:

```
typeof rrweb           = 'undefined'
!!window.__wm_dom      = false
typeof window.__wm_dom_emit = 'function'     ← binding 是在的
```

观看端 WS 上收得到 `hello` / `cast`,**DOM 事件一条都没有**。
`/api/res` 也就永远不会被请求。

**全程不报错。** 服务端日志只有正面消息:

```
sessiond 起来了 …(画面走 dom)
注入登记好了 id=4(552 KB)
DOM 记录器装上了(1 个 tab)
```

## 已经排除的

按撞见的顺序记,**每一条都是先猜错、再靠日志纠回来的** ——
留在这儿是为了下一个人别再走一遍:

| 猜过的 | 怎么排除的 |
| --- | --- |
| CDP 连接被资源抓取压死 | 量了往返:导航时 600ms 尖峰,平时 3ms,不是 30 秒 |
| `--transport` 没传到 sessiond | **是真的,已修** —— 非 VNC 那条路径漏了这个键([`process.py`](../../../webmuxd/runtime/process.py)) |
| `DomSource` 建得太晚 | **是真的,已修** —— 挪进 `Screencaster.__init__`,去掉次序依赖 |
| 注入赶不上导航(竞态) | **是真的,已修** —— `waitForDebuggerOnStart: True`,注入完再放行。binding 从"有时候没有"变成稳定有 |
| `Page` 域没开 | 补了 `Page.enable`,没变化 |
| 脚本自己抛了 | 抛了会经 binding 报 `type:-1`,日志里一条都没有 —— **它根本没执行** |

上面四条修完之后,**症状仍在**。

## 收窄到的那一点

`Page.addScriptToEvaluateOnNewDocument` 回了一个 identifier(`id=4`),
说明这条命令被那个 session 接受了。但脚本从不执行。

**最可能的解释:登记用的那个 `sessionId` 不是这个 target 当下活着的那个。**
它来自 [`Session._pending_sessions`](../../../webmuxd/serve/session.py),
由 `Target.attachedToTarget` 事件攒下来。往一个已经作废的 session 上登记,
CDP 会照常回一个 identifier —— 和"登记成功但不生效"这个症状完全吻合。

还有一处可疑,一并记下:`_pending_sessions` 和 `_waiting`
**是写在类体上的可变默认值**,所有 Session 实例共用同一个 dict/set。
单进程一个 session 时看不出来,但它本来就该是实例属性。

## 下一步该做的(**先验,别再猜**)

1. 登记之后立刻在同一个 session 上 `Runtime.evaluate("1")`,看它是不是活的
2. 对比 `_pending_sessions` 里那个 sid 和 `Target.getTargets` / 实际发
   `Input.*` 用的那个 sid 是不是同一个
3. 若不是同一个:登记改用**当前实际在用的那个 session**,并把
   `_pending_sessions` 的生命周期理清(什么时候作废、谁负责清)
4. 顺手把那两个类级可变默认值改成实例属性

## 影响面

- **JPG / VNC 不受影响**,已验;全套测试 exit 0
- `waitForDebuggerOnStart` 那个改动**本身是对的**,顺带补掉了 shim 和光标探针
  一直存在的同一个竞态 —— 即使 DOM 这条最后不要了,那个改动也该留着
- 设计稿 [c §5](../works/c-view.md#5-第三条rrweb--它不传像素) 描述的是
  **设计**,不是现状;现状以本篇为准

## 旁证:这条路本身是走得通的

[`examples/rrweb_console/`](../../../examples/rrweb_console/) 里同一套做法是跑通的
(点击、中文输入、光标白名单、延迟 0.0s 全验过)。
差别只在**注入挂在哪**:那个例子自己起 chrome、自己管 session;
产品里要挂到 webmuxd 现成的 attach 路径上。**问题出在这个接缝上,不在方案上。**
