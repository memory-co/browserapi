# v2_simple —— 一条完整的路,当样例用

**从 CLI 进,而且是真跑一个进程。** `[sys.executable, "-m", "webmuxd"]`,
不是 `from webmuxd.cli import main` 调一下 —— in-process 调函数测不出
argv 解析、退出码、stdout 那一层,而那一层出过事(入口点写错过一次,
装完 `webmuxd` 根本起不来,全套单元测试没有一条发现)。

**观察也从 CLI 进。** `snapshot` 给的 `@e1` 就是页面结构 ——
找搜索框、读框里的值、数结果条数,三件事全靠它,**一行 JS 都没有**。

**只有"人看到了什么"从观看端来。** 人是从 `/s/<id>/channel/cdp` 那条连接上
看的:画面帧、光标、模式消息都在那儿。要验人看到的东西,就得从人看的地方看。

## 它做什么

```
webmuxd has -t demo             → 退出码 3(还没有)
webmuxd start --port …          起服务
webmuxd new --id demo           加一个 session      → has 变 0
webmuxd goto -t demo baidu      打开百度            → 看到:正文、截图
webmuxd snapshot -t demo -i     这一页上有什么      → @e13 textbox …
(观看端)鼠标移到 @e13 的 bbox 上                   → 光标 default → text
webmuxd click -t demo @e13      点它
webmuxd type  -t demo @e13 …    输入
webmuxd snapshot -t demo -i     再看一眼            → 框里有字了,而且号变新了
webmuxd key   -t demo Enter     回车
webmuxd wait  -t demo --url-contains webmuxd
webmuxd snapshot -t demo        看结果              → 数 link
webmuxd click -t demo @e13      拿过期的号去点      → 退出码 4,并说清重新 snapshot
webmuxd log   -t demo --user agent                  → 谁做的、为什么,都在
webmuxd kill  -t demo           收                  → has 回 3
```

**每一步都紧跟一句"看到了什么"** —— 不是"函数返回了什么"。

## 三个 helper,两种契约

```python
run(*argv)   # 只看退出码 —— 大多数命令
out(*argv)   # 人读的那份 stdout —— capture / url
api(*argv)   # `--json` 那份,它是 API 的原始响应,所以解析它不算解析输出
```

## 为什么写它

写这一条的过程里挖出四个 bug,每一个的表现都是**什么都没发生,而且不报错**:

1. `Runtime.enable` 全项目没调过 → **光标同步在 JPG/VNC 下从来没工作过**
2. 自窗口把光标上报吃掉了 —— 光标恰恰是被我们自己派发的鼠标移动带出来的
3. `cursor: auto` 落在**空的**输入框上报箭头(没有文字节点可命中)
4. 一次重构把 `_tell_all` 改名成 `_send_all`,漏了光标那一处调用

四个都在"单元测试全绿"的情况下活着。**这就是要有这么一条的理由。**

改成全 CLI 之后又挖出两个:

5. PATH 上装着的 `webmuxd` 是**上一版**(还有 `observe`,没有 `start`)——
   in-process 调 `main()` 永远看不见这件事
6. 找搜索框只能塞一段 `querySelectorAll` 进去 —— **那是一个缺的命令被 JS 顶掉了**,
   于是有了 [`snapshot`](../../docs/v2/cli/read.md)
