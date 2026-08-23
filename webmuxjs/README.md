# webmuxjs

**这棵树是 JS 那一半。** 和 `webmuxd/`(Python)按语言分开,
不是按"前端/后端"—— 因为服务端将来也可能有一份 JS 实现
([j §2](../docs/v2/works/j-layout.md#2-顶层两棵树按语言分))。

```
webmuxjs/
├── client/    浏览器端那份 —— 人打开的那个观看页
├── sidecar/   **注进被控页面里的那一段** —— 探针,跑在别人的页面里
└── server/    JS 版服务端 —— 今天只有协议文档和一份 TODO
```

`client/` 和 `sidecar/` 的区别不是大小,是**跑在谁的页面里**:
前者是我们自己那一页,后者跑在被控的、不可信的页面里。
所以后者那几条规矩硬一些 —— 见它自己的 README。

## client

按前端工程搞:有源码分层、有构建、有测试。
**构建产物直接打进 wheel** —— `pip install` 的人不需要 Node,
Node 只在发版时要([j §4](../docs/v2/works/j-layout.md#4-webmuxjsclient按前端工程搞))。

```
npm install
npm run build     # → dist/,打包时拷进 webmuxd/_client/
npm test          # vitest,protocol/ 和 flow/ 那两层
npm run dev       # Vite,/api 和 /channel 代理到本机 sessiond
```

## sidecar

同一套工具链,同一条"产物打进 wheel"的路。

```
npm install
npm run build     # → dist/sidecar.js,打包时拷进 webmuxd/_sidecar/
npm test          # vitest + jsdom
```

**它跑在别人的页面里**,所以有两条别处没有的规矩:

- **不许读表单控件的 `value`** —— 密码框上那就是明文([`src/label.ts`](sidecar/src/label.ts))
- **一个探针塌了,不许带走其它几个** —— 凑在同一个 bundle 里之后,
  一个没接住的异常会让后面的全装不上([`src/index.ts`](sidecar/src/index.ts))

## server

**今天不实现。** 留着这个目录是因为
[`protocol/`](server/protocol/) 里那份文档不属于任何一种语言 ——
它是两边都要遵守的那份契约,今天由 Python 实现,将来谁来实现都照它。
