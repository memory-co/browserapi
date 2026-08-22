# v2_cli_session —— 两个 session,各干各的

**这是 tmux 那一半的核心承诺**:一个 server 持有多个 session,
`-t` 说的是哪一个([k](../../docs/v2/works/k-one-server.md))。

串了会怎样:两个 agent 同时在跑,**A 的点击落到了 B 的页面上,而两边都不报错**。

## 它做什么

```
webmuxd new --id alpha            两个
webmuxd new --id beta
webmuxd new --id alpha            再来一次 —— **幂等**,像 tmux new -A -s
webmuxd goto -t alpha example.com 各去各的
webmuxd goto -t beta  baidu
   url / capture                  → 地址和正文都是两回事
   click -t beta @alpha的号        → **必须报错**
   new-tab -t alpha               → beta 不该跟着多一个
   log -t beta                    → 里面不该有 alpha 去过的地方
webmuxd kill -t alpha             关掉一个
   beta 照常导航、照常读得到       → **这才是"互不影响"那一下**
```

## 最要紧的两条

1. **号不串。** `@e1` 是 session 里的号,而号里自己带着 tab
   ([RefTable](../../webmuxd/models.py))。拿 alpha 的号去 beta 上点必须报错 ——
   悄悄点中 beta 上某个元素是最难查的一类错。
2. **关掉一个,另一个照常能用。** 共享浏览器进程或事件流的实现会在这儿露馅:
   关掉 alpha 之后 beta 跟着哑掉,而且不报错。

## 它替掉了谁

替掉 `session_identity/`(已删)。那一条测的是 **SDK 那三个对象**
(`Webmuxd` / `Session` / `Tab`)的语义,从 lib 那一面进。

**要说清楚代价**:下面这几条它验过,而这一条验不到 ——

- `session(id=...)` 幂等**返回同一个 Python 对象**(不只是不报错)
- 属性读内存不发请求(`tab.url` 读那份被事件推着更新的表)
- `act()` 不抛而快捷方法抛
- tab 关掉之后属性还能读到最后的值

要补的话该开一条 `v2_sdk_*`,而不是把它们塞回 cli 这一面
([works/test.md §2](../../docs/v2/works/test.md))。

## 不在这测什么

- 一个 session 里面怎么用 —— 在 [`v2_cli_simple/`](../v2_cli_simple/)
- 端口和路由的形状 —— 在 [`one_endpoint/`](../one_endpoint/)
