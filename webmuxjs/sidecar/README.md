# sidecar —— 注进被控页面里的那一段

> **⚠ 这棵树正在被 [`../extension/`](../extension/) 逐样替代。**
> 判据是"**这件事要不要碰页面**":不用碰的一律搬去扩展 ——
> 每搬一样,"探针改变了页面环境"那条代价就小一分。
> 今天搬走的是 `open-shim`([works/l](../../docs/v2/works/l-extension.md));
> `foreground` 和 rrweb 那半排在后面。
> **每一样都等下一版发出去、验完功能完全等同,再从这儿删掉。**

和 [`client/`](../client/) 平级,同一套工具链。区别不是大小,是**跑在谁的页面里**:
`client/` 是我们自己那一页,这儿跑在**被控的、不可信的页面**里。

```
npm install
npm run build     # → dist/sidecar.js(一段 IIFE),打包时拷进 webmuxd/_sidecar/
npm test          # vitest + jsdom
npm run typecheck
```

## 里面装四样

| | 干什么 | 为什么非得在页面里 |
| --- | --- | --- |
| [`open-shim.ts`](src/open-shim.ts) | popup 转 tab | 只有页面自己调原生 `open` 才保得住 opener 关系 |
| [`input-watch.ts`](src/input-watch.ts) | 人在动没在动 + 动的是哪个东西 | CDP 派发的输入 `isTrusted === true`,外面分不出来 |
| [`cursor.ts`](src/cursor.ts) | 光标形状 | **CDP 没有「光标变了」这种事件**,帧里也不含光标 |
| [`foreground.ts`](src/foreground.ts) | 这一页是不是浏览器的前台 | **CDP 没有「tab 被激活了」这种事件**([f §3.1](../../docs/v2/works/f-tabs.md)) |

四样共用一个 binding、一次注入、一个幂等标记。
它们**互相不认识** —— 这一点是有意保持的。

## 三条这儿特有的规矩

**① 探针不许读表单控件的 `value`。**
密码框上那就是明文,而它会被写进 `log.jsonl`,`webmuxd log` 打得出来、
`webmuxd bundle` 打包带得走。判据只取 `aria-label` → `<label>` →
`placeholder` → `name`/`id`,四样都没有就返回空 —— **说不出来就不说,
不拿内容顶上**。落地在 [`label.ts`](src/label.ts),这条规矩是拿一次泄露换来的。

**② 一个探针塌了,不许带走其它几个。**
分成四段各装各的时候,一个异常只毁自己;凑进同一个 bundle 之后,
一个没接住的异常会让后面的全装不上。**合并是为了少犯错,不是为了多一种坏法**
—— 所以 [`index.ts`](src/index.ts) 里每一个单独 try 住,而且塌了要 `console.warn`,
不咽掉。

**③ 报回去的那个函数名,两边各写了一遍。**
一个在 [`wire.ts`](src/wire.ts),一个在 `webmuxd/sidecar.py`。不一样的后果特别难查:
`addBinding` 照样成功、页面里那个函数照样在、页面照样调它,**服务端一条都收不到,
而且不报错**。`tests/the_layout_holds/` 盯着这两个字符串。

## 为什么产物不压缩

这段代码跑在别人的页面里,出问题时人拿到的第一手材料就是 DevTools 里的这段源码
—— 函数名、结构、那几个正则都得认得出来。压缩省下的几 KB 换不来这个。
(注释留不住,esbuild 一律去掉;**为什么这么写全在 `src/` 里**。)
