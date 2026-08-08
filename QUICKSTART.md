# 跑一遍看看

需要 docker。**别的什么都不用装** —— chromium 和 python 都在镜像里。

```bash
docker build -t webmuxd-dev -f docker/dev.Dockerfile docker/
docker run --rm -v "$PWD":/src webmuxd-dev python /src/examples/quickstart.py
```

大概 15 秒,你会看到:

```
① 管理实例 —— 空壳,不起任何浏览器
② 起一个 session(一个 kasm/Chromium)  API :59667
③ 开一个 tab  http://127.0.0.1:56069/
   标题 '结算'   URL http://127.0.0.1:56069/
   (这两个是读内存,没发请求)
④ 按可见文字操作 —— 不用写选择器
   命中 button '提交订单'   329ms
   页面变化:出现『订单已提交』
⑤ 有歧义时给候选,而不是替你挑一个
   ok=False  not_found:「订单」 匹配到 2 个,不确定是哪个 —— 加 nth 或换个说法
   候选:'提交订单'、'取消订单'
⑥ 观测 —— 一次调用拿到喂给模型的全部东西
   [1] textbox  "手机号" = "13800000000"
   [2] button   "提交订单"
   [3] button   "取消订单"
   标注截图 6612 字节
⑦ 回看它干了什么
    10 claudecode type {'label': '手机号', 'text': '13800000000'} → 手机号
    14 claudecode click {'text': '提交订单'} → 提交订单
       出现『订单已提交』
    18 claudecode click {'text': '订单'}  ✗ not_found
```

脚本在 [examples/quickstart.py](examples/quickstart.py),自带页面服务器,不联网。

## 这四行是全部

```python
from webmuxd import Webmuxd

web  = Webmuxd(user="claudecode")                   # 空壳管理实例
sess = web.session(id="work", port=7900, runtime="process")   # 一个浏览器
tab  = sess.open("https://example.com")             # 一个页面
tab.click("提交订单")                                # 按人看得见的字操作
```

`session(id=...)` 是幂等的 —— 同一个 id 再调一次拿到同一个 session,
不会起第二个浏览器。端口必须自己传,不会替你分配
([sdk/session.md](docs/v1/sdk/session.md))。

## 命令行

同一套东西,CLI 也有:

```bash
docker run --rm -it -v "$PWD":/src webmuxd-dev sh
cd /src
python -m webmuxd install                    # 探一遍环境,记到 ~/.webmuxd.json
python -m webmuxd new -s demo -p 7900 --runtime process
python -m webmuxd new-tab -t demo -u https://example.com
python -m webmuxd click  -t demo 确定
python -m webmuxd observe -t demo
python -m webmuxd log    -t demo
python -m webmuxd kill   -t demo
```

## 关于画面

**这个镜像里没有 Xvnc,所以只有 API 没有画面。** 它会明说:

```
⚠ 本机没有 Xvnc,这个 session 只有 API 没有画面 —— 人看不了,`vnc_url` 是空的
```

人能看着、能上手接管的那个镜像(`runtime="container"`)还没做
—— 见 [works/01](docs/v1/works/01-container.md)。现在能验证的是
**操作和观测这条链路本身是通的**。

## 现在还缺什么

不藏着,免得你以为跑通了就都有了:

- kasm 生产镜像(有桌面、有 VNC、人机同屏)
- `:7800` 那个管理进程(`/api/sessions`、按 id 反代)
- `container` runtime 没在这台机器上验证过(dev 镜像里没有 docker)
- 上传下载、favicon、一次性观看链接:文档里有,代码里还没有
- CLI 的 `share` `rename` `move-tab` `start-server`

## 跑测试

```bash
docker run --rm -v "$PWD":/src webmuxd-dev pytest -q
```

大部分测试是**真的开着 chromium 跑的**,不是 mock,所以慢(约 5 分钟)。
