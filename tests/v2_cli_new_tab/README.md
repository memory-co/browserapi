# v2_new_tab —— 点一个链接,弹出来的是个 tab

和 [v2_simple](../v2_simple/) 同一条路,换掉中间那一段:
搜索 → 点百度顶栏的「新闻」。规矩在 [v2kit](../v2kit.py) 的开头。

## 它做什么

```
webmuxd new --id nt --transport jpg    起 session(无头)
webmuxd goto -t nt baidu               打开百度
webmuxd snapshot -t nt -i              找「新闻」那个 link  → @eN
(观看端)鼠标移上去                     → 光标 default → pointer
webmuxd click -t nt @eN                点它
webmuxd tabs -t nt                     → 两个 tab,新的那个 opener=t_1
webmuxd select-tab -t nt:1             切过去 → url 是 news.baidu.com
webmuxd snapshot -t nt:1 -i            新 tab 上照样能用,号接着发
webmuxd kill-tab -t nt:1               收 → 只剩一个
webmuxd log -t nt --kind tab           一开一关都在流里
```

## 为什么走无头

**两条测试各验一条腿。**

| | v2_simple | 这一条 |
| --- | --- | --- |
| transport | VNC(有头) | JPG(无头) |
| `/channel/cdp` 上的帧 | **一帧都没有**,像素走 `/channel/xpra` | **帧就从这儿来** |
| 光标 | `text`(I 型) | `pointer`(手型) |
| 为什么必须是这条 | 百度给无头弹图形验证码 | 没有搜索,不会撞验证码 |

合起来才算把画面这一面盖住了。

## 它盯着的三件事

1. **popup 一律转成 tab,而且转完还认得爹。**
   `opener` 少了,`window.close()` / `window.opener` 这一类就断了。
2. **焦点不跟过去。** 浏览器里点 `target=_blank` 会切过去,我们不切 ——
   切了就等于替调用方决定"接下来看哪个",而它可能正在别的 tab 上干活。
   要切是一条独立的命令(`select-tab`)。
3. **`@e1` 换了 tab 也接着发**,不从头来一遍。
