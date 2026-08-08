# 跑一遍看看

```bash
pip install webmuxd
webmuxd install
```

`install` 只做一件正经事:**确认 docker 能用**,然后把底座
`kasmweb/chromium` 拉下来、在上面 build 一层 `python + webmuxd`。
第一次要几分钟(底座 4 GB 左右),之后再跑就是秒回。

```console
$ webmuxd install
探测环境…
  python      3.11.2                                   ✓
  docker      29.7.2                                   ✓
拉底座 kasmweb/chromium:1.18.0 …(4 GB 左右,第一次会久)
build webmuxd/kasm-chromium:0.1.0 …(在底座上加 python + webmuxd)
  ✓ 镜像就绪

可用的 runtime:container  remote
默认:container
记录写到 /home/you/.webmuxd.json
```

## 起一个

```console
$ webmuxd new -s demo -p 7900 --vnc-port 6901 --runtime container
demo  →  画面 https://127.0.0.1:6901   API http://127.0.0.1:7900
       登录 kasm_user / SryefzYQ6lF4   (自签名证书,浏览器会拦一下)
```

**浏览器打开那个 https 地址,用打印出来的账号密码登进去** —— 你会看到一个
完整的 Chromium 桌面,鼠标键盘直接能用。密码是这次启动现生成的,只说这一次。

同时,代码从另一个口驱动**同一个浏览器**:

```console
$ webmuxd new-tab -t demo -u https://example.com
✓ t_2  Example Domain

$ webmuxd click -t demo "Learn more"
✓ click → link "Learn more"  811ms
  → https://www.iana.org/help/example-domains   出现『We provide a web service on t…』
```

第二条命令跑的时候盯着 VNC 那个窗口看 —— **页面会在你眼前跳过去。**
这就是这东西的全部意义:人和代码看的是同一个画面,不是两份。

```console
$ webmuxd observe -t demo          # 喂给模型的元素表
$ webmuxd log     -t demo          # 它都干了什么
$ webmuxd kill    -t demo          # 收工
```

## 用库

CLI 只是薄薄一层,**库才是主体**:

```python
from webmuxd import Webmuxd

web  = Webmuxd(user="me")                                      # 空壳管理实例
sess = web.session(id="demo", port=7900, vnc_port=6901,        # 一个浏览器
                   runtime="container")
print(sess.vnc_url, sess.vnc_user, sess.vnc_password)          # 人从这儿进去看

tab = sess.open("https://example.com")                         # 一个页面
tab.click("Learn more")                                        # 按人看得见的字操作
print(tab.observe().as_prompt())
```

`session(id=...)` 是幂等的 —— 同一个 id 再调一次拿到同一个 session,不会起第二个。
端口必须自己传,不会替你分配([sdk/session.md](docs/v1/sdk/session.md))。

定位不到或者有歧义的时候,它**给候选而不是替你挑一个**:

```python
r = tab.act([{"type": "click", "text": "订单"}])
r.ok          # False
r.failed      # {'error': 'not_found', 'message': '「订单」 匹配到 2 个,不确定是哪个 …'}
r.candidates  # [{'name': '提交订单', …}, {'name': '取消订单', …}]
```

## 不想开容器

`runtime="process"` 直接在本机拉起 chromium,秒起,**但没有隔离**
(页面跑在你自己机器上),而且**没有 Xvnc 就没有画面**。
`examples/quickstart.py` 走的是这条,自带一个页面服务器,不联网:

```bash
docker build -t webmuxd-dev -f docker/dev.Dockerfile docker/
docker run --rm -v "$PWD":/src webmuxd-dev python /src/examples/quickstart.py
```

## 对外只有两个口

```
        6901  KasmVNC ──→ 人
        7900  webmuxd ──→ 代码
        ──────────────────────────
        9222  CDP     ──→ 出不去(只绑容器内 127.0.0.1)
```

调试口一次都不映射出来 —— 能连上它就等于绕过 API 直接控浏览器。
两个口都**只绑 `127.0.0.1`**;要放到公网上是上层的决定,不是我们的默认。

## 现在还缺什么

不藏着,免得你以为跑通了就都有了:

- `:7800` 那个管理进程(`/api/sessions`、按 id 反代)
- 上传下载、favicon、一次性观看链接:文档里有,代码里还没有
- CLI 的 `share` `rename` `move-tab` `start-server`
- 人在 VNC 里动手时的让路(`human_yield`)只有骨架,没验过

## 跑测试

```bash
docker run --rm -v "$PWD":/src webmuxd-dev pytest -q
```

大部分测试是**真的开着 chromium 跑的**,不是 mock,所以慢(约 5 分钟)。
