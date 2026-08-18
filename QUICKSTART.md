# 跑一遍看看

```bash
pip install webmuxd
webmuxd install
```

`install` 只回答两个问题:**这个网络环境下得到那个浏览器吗、系统依赖齐吗**。
浏览器落在 `~/.cache/webmuxd/`,路径记进 `~/.webmuxd.json`。

```console
$ webmuxd install
探测环境…
  python      3.11.2                                 ✓
  浏览器        chrome 152.0.7977.42                   ✓
  共享库        齐                                      ✓
  中文字体      有                                      ✓

记录写到 /home/you/.webmuxd.json
```

**版本是钉死的** —— 每个 release 钉一个,机器之间完全一致
([works/07 §4.1](docs/v2/works/07-runtime.md))。

**下载源不用你挑** —— `install` 会并发探一遍(下真实那个文件的头 256 KB,
量的是吞吐不是 ping),自己选最快的:

```console
  下载源        探测中…
     官方               1.8 MB/s     ✓
     npmmirror        0.4 MB/s
     npmmirror cdn    0.3 MB/s
```

要指定就指定,**传进来的赢**,指定了就不探了:

```bash
WEBMUXD_BROWSER_MIRROR=https://cdn.npmmirror.com/binaries/chrome-for-testing webmuxd install
```

装依赖(要 root,只支持 Debian/Ubuntu):`webmuxd install --with-deps`。
别的发行版它只打印缺什么,**不静默**。

## 起一个

```console
$ webmuxd new --id demo --port 7900
       ⚠ 页面跑在这台机器上,**没有隔离** —— 要隔离见 docs/v2/works/07 §2
demo  →  http://127.0.0.1:7900/   (API 在同一个口:http://127.0.0.1:7900/api)
```

**如果你是 root**(云主机、容器里常见),会多一行:

```
⚠ 你是 root —— Chromium 在 root 下必须 --no-sandbox 才起得来(crbug 638180),
  已经替你加上了。**沙箱是关着的**;想要它就换个非 root 用户跑
```

这不是可选的:Chromium 在 root 下**没有开着沙箱还能跑的配置**。要沙箱就用非 root 用户。

**浏览器打开那个地址** —— 你会看到远端页面,鼠标键盘直接能用,中文输入也能用
(组字在你本地完成,提交时才发过去)。上面那条 tab 条和地址栏是**我们画的 HTML**,
不是浏览器自己的 —— 画面里只有页面内容。

同时,代码从**同一个口**驱动**同一个浏览器**:

```console
$ webmuxd new-tab -t demo -u https://example.com
✓ t_2  Example Domain

$ webmuxd click -t demo "Learn more"
✓ click → link "Learn more"  811ms
  → https://www.iana.org/help/example-domains   出现『We provide a web service on t…』
```

第二条命令跑的时候盯着那个网页看 —— **页面会在你眼前跳过去。**
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

web  = Webmuxd(user="me")                       # 空壳管理实例
sess = web.session(id="demo", port=7900)        # 一个浏览器,一个口
print(sess.view_url)                            # 人从这儿进去看

tab = sess.open("https://example.com")          # 一个页面
tab.click("Learn more")                         # 按人看得见的字操作
print(tab.observe().as_prompt())
```

`session(id=...)` 是幂等的 —— 同一个 id 再调一次拿到同一个 session,不会起第二个。
端口必须自己传,不会替你分配。

定位不到或者有歧义的时候,它**给候选而不是替你挑一个**:

```python
r = tab.act([{"type": "click", "text": "订单"}])
r.ok          # False
r.failed      # {'error': 'not_found', 'message': '「订单」 匹配到 2 个,不确定是哪个 …'}
r.candidates  # [{'name': '提交订单', …}, {'name': '取消订单', …}]
```

`examples/quickstart.py` 把上面这些串成一段,自带一个页面服务器,不联网:

```bash
python examples/quickstart.py
```

## 画面糊?先看状态栏

糊有**三个互不相干的来源,调错旋钮不会有任何效果**
([works/02 §4](docs/v2/works/02-frame-protocol.md))。页面底下那条状态栏就是
用来判断该调哪个的:

| 状态栏 | 说明 | 调哪个 |
| --- | --- | --- |
| **有效缩放 > 1.00x** | 你的屏是高 DPI,帧被**放大**了 —— 糊不是压缩造成的 | `--dsf 2`(Retina)。**调画质完全没用** |
| **画质 掉到 60 / 40**,或带 `/2` `/3` | RTT 自适应在降质(阈值 725ms),链路慢 | 链路问题,不是设置问题 |
| `1.00x` + `q80` 都正常 | 那才轮到编码 | `--quality 95` 或 `--format png` |

```bash
webmuxd new --id work --port 7900 --quality 95      # 编码那一档
webmuxd new --id work --port 7900 --dsf             # 观看端是 Retina 才开,= 2
webmuxd new --id work --port 7900 --min-quality 40  # 链路差时最多降到 40
```

**`--dsf` 默认是关的,而且它不是"越大越清晰"的旋钮** —— 它只用来匹配观看端的 dpr。
普通屏(dpr=1)上开了,实测锐度反而**低 18%**,还多花 2.6 倍带宽:原生尺寸渲染时
的抗锯齿是针对那个像素网格优化过的,放大再缩回来等于把它重新平均了一遍。
**所以只在状态栏显示有效缩放 > 1.00x 时才开它。**

`--min-quality` 是自适应最多降到多少,默认 25。再低就是马赛克 —— 到底了它会改成
抽帧,那才是链路真撑不住时该退的方向。

### 滚动不顺?那是另一回事

上面三个都是"清晰度"。**滚动顺不顺是第四件事**,而它不归上面任何一个旋钮管 ——
screencast 每帧都是整屏重发,滚动时该发多少发多少。

在意滚动的话换一条像素来源:

```bash
apt install xpra xvfb python3-pil                     # Debian / Ubuntu
# yum install xpra xorg-x11-server-Xvfb python3-pillow  # RHEL / CentOS / 阿里云
webmuxd new --id work --port 7900 --transport xpra
webmuxd info                       # 先看这台机器上可不可用
```

它按 damage 区域编码,滚动时用 `scroll` 包**零字节搬像素** —— 实测滚一页
Wikipedia,57% 的重绘面积没花一个字节
([works/12 §9](docs/v2/works/12-xpra-client.md))。

**变的只有像素从哪来**:输入、只读、tab、原生 UI、状态栏全都一样。
代价是要装那三个包(装不上就是用不了,不会悄悄退回),浏览器是有头的比较吃资源,
而且**全屏持续放视频反而是它的劣势区** —— 那种场景默认的 screencast 更合适。

`--dsf` 在 xpra 上没有用(尺寸由 X 显示定),给了会直接报错而不是被忽略 ——
要更高的分辨率就把 `--window-size` 开大。

## 给别人看

```python
sess.share()                        # 默认只读,1 小时
sess.share(writable=True)           # 可操作 —— 能碰你所有登录态
```

**只读是服务端丢弃输入**,不是前端把按钮变灰 —— 拿到只读链接的人自己写个 WS
客户端直接发也没用([works/04 §3](docs/v2/works/04-one-port.md))。

## 页面卡住的时候

headless 里浏览器自己那些原生 UI **一个像素都不会出现在画面上**,
所以它们是被 CDP 拦下来交给你的:

```console
$ curl localhost:7900/api/pending
{"dialogs": [{"id":"dlg_1","tab":"t_2","subtype":"confirm","text":"确定要删除吗?"}], …}

$ curl -X POST localhost:7900/api/tabs/t_2/dialog -d '{"accept":true}'
```

内置的那个页面会直接把这张卡画出来,点一下就行。**没人回答就超时走取消,
并且写进日志** —— 页面为什么停住、后来为什么又动了,`webmuxd log` 里查得到。

下载、文件选择、权限、Basic 认证同理,见 [works/06](docs/v2/works/06-no-desktop.md)。

## 要隔离

webmuxd **不碰容器** —— tmuxd 不会 `docker run` 一个 tmux。姿态是反过来的:
**你把 webmuxd 放进容器里**。

```dockerfile
FROM python:3.12-slim
RUN pip install webmuxd && webmuxd install --with-deps
```

或者让浏览器待在别处,只把 CDP 端点给我们:

```python
sess = web.session(id="cloud", port=7900,
                   runtime="remote", cdp="wss://chrome.example.com?token=…")
print(sess.view_url)   # 画面还是我们产的,连的是他们的浏览器
```

## 现在还缺什么

不藏着:

- 管理面那个口(`/api/sessions`、按 id 反代)
- favicon、`webmuxd share` / `rename` / `move-tab` / `start-server`
- 右键菜单、拖放上传、打印 —— 有替代路径,排在后面
- 剪贴板反向(远端复制 → 本地)只做了粘贴那一半
- RTT 自适应降质写好了但**本机验不到** —— 阈值是 725ms,得人为加延迟才触发

## 跑测试

```bash
pytest -q
```

用的就是 `webmuxd install` 下的那个浏览器。大部分测试是**真的开着它跑的**,
不是 mock,所以慢(约 5 分钟)。
