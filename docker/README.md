# 镜像 · 两个 wrapper

webmuxd 需要两个端点([works/08](../docs/v1/works/08-browser-runtime.md)):

```
一个画面端口   ← 给人
一个 CDP 端点  ← 给代码
```

现成的浏览器镜像都做好了第一个,**第二个几乎都没有** —— 因为 Chromium 把调试口
绑死在容器内的 `127.0.0.1`,而 `docker -p` 是 DNAT 到 eth0,够不着。

这里就是把第二个补上。**只加一层,不改底座的任何脚本、不换掉它的入口逻辑。**

| 镜像 | 底座 | 加了什么 |
| --- | --- | --- |
| `webmuxd/kasmweb-chromium:1.18.0` | `kasmweb/chromium:1.18.0` | 一个中继(底座没有 socat,用它自带的 python3) |
| `webmuxd/jlesage-chromium:latest` | `jlesage/chromium:latest` | **几乎什么都没加** —— 底座本来就内置了 socat 转发,只是默认关着 |

**名字保留底座的出处**(`kasmweb-` / `jlesage-`)—— 一眼看得出里面是谁的东西。

## 构建

**一个镜像一个目录**,构建上下文就是那个目录 —— 看目录就知道这个镜像由哪几个
文件构成,不用在一堆平铺的文件里对着 `-f` 猜。

```
docker/
├── kasmweb-chromium/   Dockerfile  entrypoint.sh  cdp-relay.py
├── jlesage-chromium/   Dockerfile  entrypoint.sh
└── dev/                Dockerfile              ← 跑测试用的,和上面两个无关
```

```bash
docker build -t webmuxd/kasmweb-chromium:1.18.0 docker/kasmweb-chromium/
docker build -t webmuxd/jlesage-chromium:latest docker/jlesage-chromium/
```

换底座版本用 `--build-arg BASE=...`。

## 跑

```bash
# kasmweb —— 画面 6901(自签名 https,kasm_user / $VNC_PW)
docker run -d --shm-size=1g \
  -p 127.0.0.1:6901:6901 -p 127.0.0.1:9222:9222 \
  -e VNC_PW=至少六位 -e LAUNCH_URL=https://example.com \
  webmuxd/kasmweb-chromium:1.18.0

# jlesage —— 画面 5800(http)
docker run -d --shm-size=1g \
  -p 127.0.0.1:5800:5800 -p 127.0.0.1:9222:9222 \
  -e CHROMIUM_APP_URL=https://example.com \
  webmuxd/jlesage-chromium:latest
```

两个都验过:`curl http://127.0.0.1:9222/json/version` 直接出 Chromium 版本,
webmuxd 连上去 `open` / `click` / `observe` 都正常。

### 换 CDP 对外端口

**变量名两个镜像不一样**,因为 jlesage 的底座已经有自己的名字了,而我们盖不住它
(s6 起服务时按镜像 env 重建环境,`cont-env.d` 只提供默认值)。
与其造一个盖不住的别名,不如让**标签**说清楚该设哪个:

```bash
docker run … -e WEBMUXD_CDP_PORT=9333            -p 127.0.0.1:9333:9333 webmuxd/kasmweb-chromium:1.18.0
docker run … -e CHROMIUM_REMOTE_DEBUGGING_PORT=9444 -p 127.0.0.1:9444:9444 webmuxd/jlesage-chromium:latest
```

```bash
docker inspect -f '{{index .Config.Labels "webmuxd.cdp.port_env"}}' <镜像>
```

## ⚠ kasmweb 在 `--network host` 下一台机器只能跑一个

KasmVNC 内部用 `.KasmVNCSock<pid>` 这个**抽象 unix socket** 做会合点
([TcpSocket.cxx](https://github.com/kasmtech/KasmVNC) 里 `sprintf(sockname,
".KasmVNCSock%u", getpid())` + `sun_path[0] = '\0'`)。抽象 socket **归 network
namespace 管**,而名字来自 Xvnc 的**容器内 PID** —— 每个 kasm 容器启动流程一样,
PID 也一样,于是共享 netns 的第二个容器必然撞名:

```
(EE) vncExtInit: failed to bind socket: Address already in use (98)
```

上游 [kasmtech/KasmVNC#363](https://github.com/kasmtech/KasmVNC/issues/363) 开着,
还没被诊断出原因。`--pid host` 能让 PID 唯一,但会让 kasm 的 `pgrep chromium`
误判、第二个浏览器不启动 —— **解开一个就绑住另一个**。

所以:

- **bridge 网络下想开几个开几个**,这是默认走法,不受影响
- **要 `--network host`**(为了让容器里的 `localhost` 就是宿主机的),
  kasmweb 只能一个;要一机多开就用 `webmuxd/jlesage-chromium`

jlesage 那个没这个问题 —— 它给 Xvnc 的是 `-nolisten local -rfbunixpath=…`:
X 的抽象 socket 关掉了,RFB 走**文件系统**上的 socket,抽象命名空间里只剩内核给的
匿名 autobind,**一个自己起名字的都没有**。(`-rfbport` 不在这条判据里 ——
端口撞了改一下就好,名字撞了没得改。)实测两个容器共享 host netns 同时跑,
画面和 CDP 都正常。

标签里写着这件事:

```bash
docker inspect -f '{{index .Config.Labels "webmuxd.host_network"}}' <镜像>
# kasmweb → single      jlesage → multi
```

## 标签:把 profile 做成机器可读的

[works/08 §5](../docs/v1/works/08-browser-runtime.md) 说接一个新镜像只需回答五个
问题。那五个答案就写在标签里,**调用方 `docker inspect` 就知道这镜像长什么样,
不用改 webmuxd 的代码**:

| 标签 | 意思 |
| --- | --- |
| `webmuxd.window.port` / `.scheme` | 画面在哪个口、什么协议 |
| `webmuxd.window.port_env` | 改画面端口的变量名(空 = 只能靠 `-p`) |
| `webmuxd.window.user` / `.user_env` | 登录名是写死的,还是某个变量定的 |
| `webmuxd.window.password_env` | 口令从哪个变量来 |
| `webmuxd.cdp.port` / `.port_env` | CDP 默认口、改它的变量名 |
| `webmuxd.chromium.args_env` | 往 Chromium 塞参数的变量名 |
| `webmuxd.chromium.url_env` | 启动页的变量名 |
| `webmuxd.host_network` | `multi` = 能一机多开;`single` = host 网络下只能一个 |

## 加第三个镜像

写一个新的 Dockerfile,回答同样那几个问题:

0. **新建一个目录** `docker/<出处>-<应用>/`,Dockerfile 和它要的文件都放里面
1. **CDP 怎么出来** —— 底座自带转发就打开它(像 jlesage);没有就补一个中继
   (抄 `kasmweb-chromium/cdp-relay.py`,只依赖镜像里有 `python3`)
2. **怎么往 Chromium 塞 `--remote-debugging-port`** —— 找到它注入参数的那个变量,
   **别覆盖调用方已有的值**,追加
3. **把标签填全**

接之前先量三件事,都在现场咬过人:

- **参数是不是真进去了。** 别信变量名,`docker exec … cat /proc/net/tcp` 看
  `0100007F:2406` 在不在。写错的变量 docker 会照收,然后**静默忽略**
- **有没有用带名字的抽象 socket。** `grep -oE '@[^ ]+' /proc/net/unix` ——
  这决定它能不能共享 netns
- **启动脚本假设了什么。** kasm 的 `vnc_startup.sh` 死等一张叫 `eth*` 的网卡,
  换个网络模式就死循环,而症状是"容器 Up、日志停住、没有任何报错"

## 另一个文件

`dev/` 和这两个无关 —— 那是跑测试用的(alpine-chrome + python),
见 [QUICKSTART](../QUICKSTART.md)。
