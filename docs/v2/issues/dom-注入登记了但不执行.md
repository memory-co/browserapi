# DOM 那条画面:注入登记成功,脚本从不执行

**状态**:**已解决**(2026-08-20)。DOM 模式跑通,观看端收到完整的
`Meta → 全量快照 → 增量` 序列。
**留档理由**:真因和一路上猜的**全都不是一回事**,而这类"不报错、只是不工作"
的失败最贵。下次再遇到同一类症状,先看最后那节。

## 症状(当时)

`--transport dom` 起的 session,页面里探不到记录器,观看端一条 DOM 事件都没有。
**全程不报错**,日志只有正面消息:

```
sessiond 起来了 …(画面走 dom)
注入登记好了 id=4(552 KB)
DOM 记录器装上了(1 个 tab)
```

## 真因:两个,都在"注入"这一步

**① `addScriptToEvaluateOnNewDocument` 只对之后创建的文档生效,
而 attach 常常发生在导航之后。**

决定性的一次测量:登记之后立刻在同一个 session 上问一句 `location.href` ——

```
注入登记好了 id=4(552 KB)sid=E71B025F
  这个 session 活的,当前 URL='https://example.com/'
```

session 是活的,**但页面已经在目标页了**。于是那段脚本在等一个永远不会来的
"下一个文档"。修法:登记之余,**给当前这一页补一次 `Runtime.evaluate`**。

**② binding 不一定活过导航。**

补完注入之后记录器确实跑起来了(`typeof rrweb === 'object'`),
**但 `window.__wm_dom_emit` 是 `undefined`** —— 于是 `emit` 抛进
记录器自己的 `try/catch`,事件被静默丢掉。表现和"根本没注入"一模一样。
修法:补注入之前把 `Runtime.addBinding` 再调一次(幂等)。

## 一路上猜错的,以及怎么纠回来的

**每一条都是先猜、后被数据推翻**。留着是提醒:这类问题靠推理走不通。

| 猜的 | 怎么被推翻的 |
| --- | --- |
| CDP 连接被资源抓取压死 | 量往返:导航时 600ms 尖峰,平时 3ms —— 不是 30 秒 |
| 登记用的 sessionId 是死的 | 直接在那个 session 上求值,**活的**,而且顺带暴露了真因(URL 已经是目标页) |
| 552 KB 的 `evaluate` 会挂住 | 直接量:**5.4 秒就回来了**。之前挂住是另一个上下文(启动期争用) |

顺带查出来并已修的三个真 bug:

- **`--transport` 没传到 sessiond**(非 VNC 那条路径漏了这个键)——
  `--transport dom` 一路顺利起来,而 sessiond 用的是默认 jpg
- **`DomSource` 建得太晚**(在 `start()` 里),tab 的 attach 可能更早 → 漏装
- **注入赶不上导航的竞态** → `waitForDebuggerOnStart: True`,注入完再放行。
  这个改动**顺带补掉了 shim 和光标探针一直存在的同一个洞**

## 留下的教训

1. **"登记成功"不等于"会执行"。** `addScriptToEvaluateOnNewDocument` 回一个
   identifier 只说明命令被接受了。要验的是**页面里那个符号在不在**。
2. **吞异常的 `try/catch` 会把这类问题藏死。** 记录器 `emit` 里那个
   `catch (_) {}` 让"binding 不在"变成了完全无声。现在页面里抛的错会经
   binding 报回来(`type: -1`),服务端打日志。
3. **先验,再改。** 这一条在 issue 第一版里就写了,而真正解决它的正是
   那次"活性检查" —— 它同时否掉了假设、给出了真因。

## 还没做的(不影响用)

- **中途切到 DOM 时,当前页仍要等下一次导航** —— `switch()` 里现在只打一条
  告警。补注入那条路是现成的,接上去即可([c §9.4](../works/c-view.md#94-切到-dom-要先把记录器注进去))
- `_pending_sessions` / `_waiting` **是写在类体上的可变默认值**,所有 Session
  实例共用。单 session 时看不出来,但本来就该是实例属性
- DOM 的事件现在**搭在 `/channel/cdp` 上**,还没独立成 `/channel/dom`
