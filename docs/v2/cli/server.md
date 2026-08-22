# cli · 会话与服务

**这一层完全照 tmux。** 一个 server 持有全部 session,session 是它下面的
`/s/<id>/`([k](../works/k-one-server.md))。

```bash
webmuxd server start   --port 7900 [--bind 127.0.0.1]
webmuxd new     --id demo [--transport vnc|jpg|dom] [--url URL] …
webmuxd ls
webmuxd attach  -t demo [-p]
webmuxd has     -t demo
webmuxd kill    -t demo
webmuxd server stop
webmuxd info
webmuxd install [--force] [--with-deps] [--mirror URL]
```

## 0. 为什么只有起/停/重启收成二级

**别的都平铺。** `click` / `goto` / `snapshot` 一天打几十遍,
`webmuxd do click` 只是让每一次都更长。tmux 和 agent-browser 也都这样 ——
**热的动词平铺,成组的收进二级**(agent-browser 的二级全是冷的:
`get` / `is` / `mouse` / `set` / `network` / `storage` …)。

server 这三个非收不可,因为**它撞了名字**:

> `start` 是我们自己发明的 —— tmux 没有 `start`,它的 server 隐式起;
> 我们因为[端口必须显式给](#1-start-是显式的)才加了它。
>
> **发明了 `start`,就欠一个 `stop`。** 而 `stop` 被页面那个"停止加载"占着。
> 于是一个刚 `start` 完的人打 `stop`,拿到的是「这个 server 上还没有 session」——
> **方向完全反了。**

收进二级之后这条歧义自己没了:**server 的东西全在 `server` 底下**,
所以裸的 `stop` 不可能是 server 的。

搬走的旧名字会说自己搬去哪了,不是让人回 `--help` 里找:

```console
$ webmuxd start --port 7900
✗ bad_request: server 那一族收成二级了:`webmuxd server start --port 7900`
$ webmuxd kill-server
✗ bad_request: → `webmuxd server stop`
```

`info` 没跟着搬 —— 它答的是"这台机器和这个 server 什么情况",
不是对 server 的操作。

## 1. `start` 是显式的

agent-browser 的 daemon **按需自启**,闲置一小时自己退出。我们不这么做:

> tmux 能自启是因为它用 socket,**没有端口要挑**;我们有一个口,
> 而这个项目那条规矩是「端口由你给」([h §6](../works/h-runtime.md#6-端口由你给))——
> 替你猜一个只会让配置和实际对不上。

没起 server 时 `new` 报错并说该跑哪一行,**不偷偷起一个**:

```console
$ webmuxd new --id demo
✗ session_not_found: 没有在跑的 server —— 先 `webmuxd server start --port 7900`
```

### `server restart`

停掉再起来,**端口沿用记着的那个**:

```console
$ webmuxd server restart
server  →  http://127.0.0.1:7900/   (还没有 session:webmuxd new --id demo)
  (顺带停掉了 1 个 session —— 它们不会跟着回来)
```

两处讲究:

- **端口不重新挑。** 端口是部署决定的,重启时替你换一个等于让配置和实际
  对不上。记录里读不到就说清楚,不猜。
- **等那个口真的放开再起。** `kill_server()` 回来只表示"命令送到了",
  进程还在收尾、端口还占着 —— 立刻 start 会撞 `port_in_use`,
  而那句话对着一个刚打了 `restart` 的人是没意义的:
  **他要的口就是那个。**(第一版就是这么红的。)
- **session 不跟着回来**,所以那一行要说出来 —— 不然人以为 restart 是
  "原样恢复"。

🔲 **待讨论:闲置自动退出。** agent-browser 有 `--idle-timeout`。
我们没有 —— 而 tmux 也没有。要不要,取决于"webmuxd 是常驻服务还是随手起的工具"。

## 2. session 是一等命令,不是一个 flag

agent-browser 用 `--session <name>` 这个**全局 flag** 区分会话,
会话本身没有生命周期命令(daemon 帮你管)。

我们把它抬成命令:`new` / `ls` / `kill` / `attach`。理由是形态那条 ——
**tmux 的 session 是你会去 attach、去 ls、去 kill 的东西**,不是一个参数。

`-t session[:tab]` 一个语法同时寻址会话和标签页:

```bash
webmuxd click -t work "登录"          # work 的当前 tab
webmuxd click -t work:2 "登录"        # work 的第 3 个 tab
webmuxd click -t work:t_7 "登录"      # 按 tab id
webmuxd click -t work:购物车 "登录"    # 按标题(本地匹配)
```

**只有一个 session 时 `-t` 可以省**;有多个就必须给 —— **不猜**,
点错浏览器的代价比敲错终端大。

## 3. `attach` 打开的是本来就在的那个口

```console
$ webmuxd attach -t demo
http://127.0.0.1:7900/s/demo/        # 顺手用默认浏览器打开
$ webmuxd attach -t demo -p          # 只打印,不开(无 GUI 环境)
$ webmuxd attach                     # 不给 id 就开那张 session 列表
```

agent-browser 那边对应的是 `dashboard start`(另起一个 web UI)。
我们不需要 —— **画面口一直在**,`attach` 只是把地址交给你。
这是形态那条的直接后果:ttyd 也是这样,`-p` 起来就在,不用再"打开面板"。

## 4. `-L` / `-H`:换一套,或者连远端

```bash
webmuxd -L ci start --port 7901       # 另一套互不可见的 server(同 tmux -L)
webmuxd -H http://box:7900 ls         # 连别人机器上的
```

登记的只有一行"server 在哪个口上"。**文件会撒谎**(进程被 OOM 杀了它不知道),
所以按记录去连、连不上就当没有。

## 5. `info` / `install`

```console
$ webmuxd info
版本      0.9.0
runtime   process, remote
画面      VNC(默认),JPG,DOM
server    http://127.0.0.1:7900/  (2 个 session)
记录      2026-08-21T22:49:49Z(webmuxd install 探的)
```

`install` 对应 agent-browser 的 `install`:下 Chrome for Testing、
装系统依赖、**写一份路径表**([d](../works/d-install.md))。

🔲 **待讨论:`doctor`。** agent-browser 有 `doctor [--fix]`。
我们的 `info` 只报**现状**,不诊断也不修。差的是"这台机器为什么起不来"
那套判断 —— 而那些判断今天散在 `install` 和起 session 的报错里。
