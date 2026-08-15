# webmuxd/jlesage-chromium

底座 [`jlesage/chromium`](https://hub.docker.com/r/jlesage/chromium) —— TigerVNC + noVNC。
画面体验不如 kasm([works/08 §4](../../docs/v1/works/08-browser-runtime.md)),
但它有一样 kasm 没有的:**`--network host` 下能一机多开**。

**这一层几乎什么都没加。**

## 底座本来就把 CDP 送出来了

它内置了一个转发服务,只是默认关着:

```sh
exec socat TCP-LISTEN:${CHROMIUM_REMOTE_DEBUGGING_PORT},fork \
           TCP:127.0.0.1:$((CHROMIUM_REMOTE_DEBUGGING_PORT + 1))
```

和 [kasm 那边](../kasmweb-chromium/README.md#-补上-cdp-端点)我们手写的中继是同一个
思路,只是人家用 socat 而且做进镜像了。所以这一层只做两件小事:

1. `ENV CHROMIUM_REMOTE_DEBUGGING=1` —— 默认打开它
2. entrypoint 把统一的 `WEBMUXD_*` 端口名翻译成底座认的名字

**开关必须是镜像 `ENV`,不能在 entrypoint 里 export** —— 底座决定"这个服务要不要
起"是在读镜像 env 那一步,比 entrypoint 更早。端口反过来:它是服务起来之后才用的,
`export` 就够(实测)。

## 为什么它能一机多开

它给 Xvnc 的参数里有 `-nolisten local`(关掉 X 的抽象 socket)和
`-rfbunixpath=…`(RFB 走**文件系统**上的 socket)。于是抽象命名空间里只剩内核给的
匿名 autobind(`@f0fa9` 这种五位十六进制,天生各不相同),**一个自己起名字的都没有**。

而 [kasm 那边](../kasmweb-chromium/README.md#-network-host-下一台机器只能跑一个)
的 `.KasmVNCSock<pid>` 正相反 —— 名字来自 PID,共享 netns 必撞。

> `-rfbport` 不在这条判据里(实测见过 `5900` 也见过 `-1`)。**端口撞了改一下就好,
> 抽象 socket 的名字撞了没得改** —— 这才是分界。

## 这个镜像自己的变量

统一的 `WEBMUXD_VIEW_PORT` / `WEBMUXD_CDP_PORT` 见 [../README.md](../README.md)。
底座的变量原样可用,常用的:

| | |
| --- | --- |
| `DISPLAY_WIDTH` / `DISPLAY_HEIGHT` | 分辨率 |
| `CHROMIUM_CUSTOM_ARGS` | 追加给 Chromium 的参数 |

**画面口令用统一的 `WEBMUXD_PASSWORD`**,用户名用 `WEBMUXD_LOGIN`(默认 `webmuxd`),
绑定地址用 `WEBMUXD_BIND`。

底座的 `WEB_LOCALHOST_ONLY` 是个**布尔**(只听 loopback 与否),所以 wrapper 把
地址翻译成布尔 —— 它表达不了"绑某个具体网卡",而我们也只需要这两种。

给了口令时 wrapper 会**顺手把 `SECURE_CONNECTION=1` 也开上** —— 这个底座
要求"开认证就必须走 https",否则容器启动直接退出,而报错埋在一堆 cont-init
日志中间,不看到底翻不出来。既然口令是我们要求的,这个就替调用方开掉。

所以这个镜像的画面也是 **https(自签名)**,和 kasm 一致。

### 它的鉴权不是 basic auth

看过镜像里的 `auth.conf` 和 `10-webauth.sh`:这一版用 nginx 的 **`auth_request`**
模块 —— 每个请求发一个内部子请求去校验,校验方靠 **cookie 里的 token** 判断;
没通过就 302 到登录页,登录成功才发 cookie。

**没有 basic auth 这个选项。** 所以拿 `curl -u` 去探会看到 302,那是跳登录页,
不是口令没生效 —— 我第一次就被这个骗过。

底座还有个 `WEB_AUTHENTICATION_ALLOW_INSECURE=1`,能在 http 下开认证(它自己会打
一大段警告说凭据和 token 明文传输)。**我们特意不用**:既然要口令,就别让它裸奔。

不想要鉴权就别给 `WEBMUXD_PASSWORD` —— 底座默认就是不开。但默认跑法是
`--network host`,而这个底座的窗口绑 `0.0.0.0`,**不设口令等于把一个能操作的
浏览器直接放出去**。

**没有"启动页"这个变量。** 它只有 `CHROMIUM_APP_URL`,而那个映射到 `--app=`
(无边框应用窗口),不是普通启动页 —— 所以标签里 `chromium.url_env` 是空的,
由 webmuxd 连上之后自己 `open()`。**profile 宁可缺一项,也不填一个语义不对的。**
