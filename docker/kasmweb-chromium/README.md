# webmuxd/kasmweb-chromium

底座 [`kasmweb/chromium`](https://hub.docker.com/r/kasmweb/chromium) —— **三种画面实现里体验最好的那个**
([works/08 §4](../../docs/v1/works/08-browser-runtime.md))。窗那一半原样是它的:
KasmVNC、自签名 https、`kasm_user` + 口令。

这一层只补两件**原厂镜像跑不起来的事**。

## ① 补上 CDP 端点

Chromium 把调试口绑死在容器内的 `127.0.0.1`,而 `docker -p` 是 DNAT 到 eth0 ——
那上面没人听,所以直接映射是个死口。底座又没有 `socat`,于是用它自带的 `python3`
起一个二十行的中继(`cdp-relay.py`):

```
0.0.0.0:$WEBMUXD_CDP_PORT  ──→  127.0.0.1:$((WEBMUXD_CDP_PORT + 1))
                                 ↑ Chromium 听在这儿
```

调试口是 entrypoint 追加进 `APP_ARGS` 的 —— **不能直接覆盖**那个变量:
kasm 那边是 `ARGS=${APP_ARGS:-$DEFAULT_ARGS}`,我们一设,它自己的默认值就整个没了。

## ② 让它在 `--network host` 下起得来

kasm 的启动脚本里有个死循环:

```bash
for interface in $interfaces; do
    if [[ $interface == eth* && -z $KASM_SVC_EGRESS ]]; then return; fi
done
sleep 1        # 认不出就永远转下去
```

它**死等一张名字以 `eth` 开头的网卡**。bridge 下 docker 正好这么命名,所以这行
从来没暴露过;`--network host` 下容器看到的是宿主机的真实网卡(`ens4` /
`enp0s3` …,现代 Linux 基本都不叫 eth0),于是 Xvnc 和 Chromium 一个都起不来 ——
**而症状是"容器 Up、日志停住、没有任何报错"**。

所以这一层 `sed` 掉了那个循环。**这是要改底座一行启动脚本的**,代价是 kasm 升
版本要复核这个锚点还在不在。没有别的办法 —— 那个循环没有开关。

**补丁打不上就让 build 失败**,绝不静默留一份没改的:那会在运行时卡死,
而报错指向别处。

## ⚠ `--network host` 下一台机器只能跑一个

KasmVNC 内部用 `.KasmVNCSock<pid>` 做会合点
([`TcpSocket.cxx`](https://github.com/kasmtech/KasmVNC)):

```c
sprintf(sockname, ".KasmVNCSock%u", getpid());
addr.sun_path[0] = '\0';                 // ← 抽象命名空间
```

抽象 unix socket **归 network namespace 管**,名字来自 Xvnc 的**容器内 PID**。
每个 kasm 容器启动流程一样 → PID 也一样 → 共享 netns 的第二个容器必然撞名:

```
(EE) vncExtInit: failed to bind socket: Address already in use (98)
```

**这个绕不过去**,不像 ② 那样能 patch —— 名字编译在 KasmVNC 二进制里。
上游 [kasmtech/KasmVNC#363](https://github.com/kasmtech/KasmVNC/issues/363) 还开着。

(`--pid host` 能让 PID 唯一,但会让 kasm 的 `pgrep chromium` 误判、第二个浏览器
不启动 —— 解开一个就绑住另一个。)

**要一机多开**:用 [jlesage 那个](../jlesage-chromium/),或者加 `--network bridge`
(代价是容器里的 `localhost` 不再是你的)。

## 这个镜像自己的变量

统一的 `WEBMUXD_VIEW_PORT` / `WEBMUXD_CDP_PORT` 见 [../README.md](../README.md)。
除此之外底座的变量原样可用,常用的:

| | |
| --- | --- |
| `LAUNCH_URL` | 启动页 |
| `APP_ARGS` | 追加给 Chromium 的参数(我们会在后面接上调试口) |

**画面口令用统一的 `WEBMUXD_PASSWORD`**(wrapper 翻译成底座的 `VNC_PW`),
**至少 6 位** —— 短了容器直接退出,而报的错是 `kill: usage:`、和密码毫无关系。

**用户名是 `kasm_user`,改不了** —— KasmVNC 写死的。

**`WEBMUXD_BIND` 也是 patch 出来的。** 底座把 `-interface 0.0.0.0` 写死在同一个
启动脚本里(和那个死循环一个文件),build 时一起 `sed` 成变量。

## 已知没做到:桌面分辨率改不了

`WEBMUXD_WINDOW_SIZE` 这个镜像**不声明**(标签里没有 `webmuxd.window_size.env`),
所以 webmuxd 不会去设它 —— 桌面固定在底座默认的 **1024×768**。

**不是没接。** 已经排除的:

- 环境变量到得了容器(`VNC_RESOLUTION=1280x800`),用容器级 `-e` 直接设也一样不生效
- 启动脚本里只有一条真实的 `vncserver` 调用,而且确实写着 `-geometry $VNC_RESOLUTION`
- `~/.vnc/config` 和默认 profile 里的 `.vnc/` 都没有覆盖它
- `vncserver` 那个 perl 脚本的选项解析是正常的
  (`if ($opt{'-geometry'}) { $geometry = $opt{'-geometry'}; }`),
  `1024x768` 是它在 `DefineFilePathsAndStuff` 里的**内置默认**

顺带在[上游 Dockerfile](https://github.com/kasmtech/workspaces-core-images/blob/master/dockerfile-kasm-core)
里看到一处怪事:同一个 `ENV` 块里 **`VNC_RESOLUTION` 被声明了两次**
(`1280x1024` 和 `1280x720`,后者胜出)。这解释了容器里为什么看到 `1280x720`,
但解释不了最终的 `1024x768`。

**最合理的解释是那一行执行时 `$VNC_RESOLUTION` 是空的** —— 那样命令会变成
`-geometry -websocketPort <口> …`,perl 那边当没给值、回落到内置默认。
但为什么会是空的,我没能证实(脚本里没有任何地方给它赋过值)。

**在挖清楚之前不声明这个能力** —— 声明了就等于让调用方以为设过了,
而画面和截图尺寸对不上是最难查的那类问题。

[jlesage 那个](../jlesage-chromium/README.md)可以:`DISPLAY_WIDTH/HEIGHT` 直接生效。
