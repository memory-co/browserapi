# DOM 那条画面:导航一次就死,而且不报错

**状态**:**已修**(2026-08-21)。两个 bug,一个盖着另一个。
**留档理由**:[上一篇](dom-注入登记了但不执行.md) 修完之后 DOM 是通的,
后来又悄悄死了 —— 而"悄悄"正是这条链路的固有毛病:
`emit` 外面包着 `try/catch`,发不出去和页面没动**长得一模一样**。

## 症状

`--transport dom` 起的 session,`/channel/rrweb` 连得上、握手正常,
**一条事件都不来**。日志里全是正面消息:

```
sessiond 起来了 …(画面走 dom)
DOM 记录器装上了(1 个 tab)
当前页补上记录器了
GET /channel/rrweb 101
```

## 怎么定的位

**先量,再改**(上一篇的教训)。拿 session 自己的 CDP 端点连进被观看的那一页:

```
{"url":"http://…/","rrweb":"object","wm":1,"emit":"undefined"}
```

记录器在(`rrweb` 是 object、`__wm_dom` 是 1),**而 binding 不在**。
于是 `emit` 抛进那个 `catch (_) {}`,事件被静默丢掉。

接着量了第二下 —— 这一下是决定性的:

```
现在                        : emit = undefined
我这条 session 上 addBinding 之后 : emit = function
导航之后                     : emit = undefined
```

**`Runtime.addBinding` 装的是当前那个执行上下文里的一个函数,不活过导航。**
上一篇里写的是"binding 不一定活过导航",于是只在 arm 那一刻补了一次 ——
**它不是"不一定",是每次都不活。**

## 两个真因

**① `Runtime.enable` 从来没调过。**

`grep -rn "Runtime.enable" webmuxd/` —— **一处都没有**。
而 `Runtime.bindingCalled` 和 `Runtime.executionContextCreated`
都只在这个域开着的时候才推。不开的话:`addBinding` 照样成功、
页面里那个函数照样在、页面照样调它 —— **而服务端一条都收不到,还不报错**。

这一条最阴:所有"命令"都成功,只有"事件"不来。

**② binding 每次导航都没了,而页面脚本比补 binding 早。**

修法只能是两边配合:

- 服务端订 `Runtime.executionContextCreated`,**每个新文档补一次 binding**
- 页面里那段脚本**先攒着**:`__wm_dom_emit` 还不是函数就压进队列,
  到了再一起发。因为它是 document-start 的,**必然比服务端补 binding 早**

顺带把那个吞异常的 `catch (_) {}` 拆了:攒满了就整个丢并报一条 ——
**不从中间截**,增量链断在中间,重放出来的 DOM 从此是错的
([c §5.5](../works/c-view.md#55-背压不能沿用丢旧保新)),那比画面停住难查得多。

## 验收

导航之后重新连上去,收到的是完整的一轮:

```
第一次导航后 : 15 条,类型 [4, 2, 3, 3, 3, …]
第二次导航后 : 10 条,类型 [4, 2, 3, 3, 3, …]
```

`4` 是 Meta,`2` 是全量快照,`3` 是增量 —— 每次导航都从头来一轮,对的。

真浏览器打开观看页也过了:`rrweb` 加载、重放器渲染出内容、
点那个输入框再敲三个字,`/api/observe` 里那个 textbox 的值变成 `hey`。

## 教训

1. **"命令成功"不等于"事件会来"。** 这条链路上,
   `addBinding` 和 `bindingCalled` 中间隔着一个从没人调过的 `Runtime.enable`
2. **吞异常的 `try/catch` 让这类问题永远查不动。** 上一篇就写过一次,
   这次是同一个 `catch (_) {}` 又藏了一次 —— 所以这回把它拆了
3. **"不一定"这种措辞是个信号。** 上一篇写"binding 不一定活过导航",
   说明当时没量清楚;量清楚了它就是"每次都不活",而那对应的是完全不同的修法
