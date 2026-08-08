# 02 · API 与 Python lib

**Python lib 就是 HTTP API 的一层薄封装**,不是第二套实现。API 有什么,lib 就有什么,名字一一对应。

鉴权:设了 `WEBMUX_TOKEN` 就带 `Authorization: Bearer <token>`,没设就不用。就这一种。

## 1. Python lib

```bash
pip install webmux
```

```python
from webmux import Browser

b = Browser("http://localhost:7900", token="changeme")

b.goto("https://shop.example.com")
b.click("登录")                            # 按可见文字找
b.type("手机号", "13800000000")            # 按标签找输入框
b.type("密码", "hunter2")
b.click(role="button", name="登录")        # 说不清的时候加 role
b.wait_for(url_contains="/home")

print(b.url, b.title)
print(b.text())                            # 页面正文
rows = b.extract(".cart-item", mode="table")
b.screenshot("cart.png")
```

顺手起容器(内部就是 `docker run`,不想用就别用):

```python
b = Browser.start(name="work", port=7900, volume="webmux-work")
print(b.view_url)      # http://localhost:7900 —— 拿去浏览器里看
```

### 定位元素

按能用就行的顺序:

```python
b.click("提交订单")                  # 可见文字(最常用)
b.click(role="button", name="登录")  # role + 名字,消歧
b.click(el)                          # observe() 拿到的元素对象
b.click(css="#pay")                  # CSS 选择器,逃生舱
b.click(at=(890, 632))               # 坐标,最后手段
```

找不到不会静默失败,抛 `NotFound` 并**附上最像的 3 个候选**:

```python
try:
    b.click("提交订单")
except NotFound as e:
    print(e.candidates)   # [button "提交订单(2)", link "订单", button "提交"]
```

### 给 Agent 用

```python
obs = b.observe()          # 一次调用拿到喂给模型的全部东西

obs.screenshot             # PNG bytes,已经在图上标好了元素编号
obs.elements               # 元素列表
print(obs.as_prompt())
# [3]  button   "提交订单"
# [4]  textbox  "优惠码" = ""
# [5]  link     "返回购物车"   (需下滑)

action = my_llm(goal, image=obs.screenshot, elements=obs.as_prompt())
b.click(obs[action.index])          # 按模型给的编号点
```

`observe()` 做的事:抓可访问性树 → 筛出能交互又看得见的元素 → 在截图上画框标号
(Set-of-Mark)。这是让多模态模型能直接用的最小观测层,不需要你自己解析 DOM。

## 2. HTTP API

所有路径在 `/api` 下,和查看页面同一个 origin。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/status` | url / title / 标签页 / Chrome 是否活着 |
| `POST` | `/api/act` | 执行动作(单个或一串) |
| `GET` | `/api/observe` | 元素表 + 标注截图 |
| `GET` | `/api/screenshot` | `?full_page=true` |
| `GET` | `/api/text` | 页面正文 |
| `GET` | `/api/log` | 操作日志,`?limit=&after=` |
| `GET` | `/api/events` | WS,实时事件流 |
| `POST` | `/api/upload` | 传文件进去给 `upload` 动作用 |
| `GET` | `/api/download/{name}` | 取下载的文件 |
| `POST` | `/api/reset` | 清 cookie、关多余标签、回 about:blank |

```jsonc
// POST /api/act
{ "actions": [
    { "type": "click", "text": "登录" },
    { "type": "type",  "label": "手机号", "text": "13800000000" },
    { "type": "key",   "key": "Enter" }
] }

// → 200
{ "results": [
    { "ok": true, "duration_ms": 412,
      "hit": { "role": "button", "name": "登录", "bbox": [820,612,140,40] },
      "after": { "url": "/home", "changed": "出现『欢迎回来』" } },
    { "ok": true, "duration_ms": 88 },
    { "ok": true, "duration_ms": 1240, "after": { "url": "/home" } }
] }
```

串行执行,遇错即停。错了返回:

```jsonc
{ "ok": false, "error": "not_found", "message": "找不到「提交订单」",
  "candidates": [ { "role":"button", "name":"提交订单(2)" }, ... ] }
```

## 3. 动作表

| 动作 | 参数 | lib |
| --- | --- | --- |
| `goto` | `url` | `b.goto(url)` |
| `back` / `forward` / `reload` | — | `b.back()` … |
| `click` | 定位 + `button`, `count` | `b.click(...)` |
| `hover` | 定位 | `b.hover(...)` |
| `type` | 定位 + `text`, `clear` | `b.type(...)` |
| `key` | `key`, `modifiers` | `b.key("Enter")` |
| `select` | 定位 + `value` | `b.select(...)` |
| `check` | 定位 + `checked` | `b.check(...)` |
| `upload` | 定位 + `file` | `b.upload(...)` |
| `scroll` | `dy` 或定位(滚到某元素) | `b.scroll(...)` |
| `wait_for` | `text` / `css` / `url_contains` / `ms` | `b.wait_for(...)` |
| `extract` | 定位 + `mode`(text/html/table/attr) | `b.extract(...)` |
| `screenshot` | `full_page` | `b.screenshot()` |
| `observe` | — | `b.observe()` |
| `tab` | `new` / `switch` / `close` | `b.tab(...)` |
| `js` | `expression` | `b.js(...)` |

`js` 和坐标点击是逃生舱:能用,但日志里会标黄 —— 因为回看的时候,
"执行了一段 JS"和"在 (890,632) 点了一下"都是看不出干了什么的。

## 4. 错误

| 错误 | 意思 | lib 异常 |
| --- | --- | --- |
| `not_found` | 找不到元素(带候选) | `NotFound` |
| `not_clickable` | 找到了但被挡住/禁用 | `NotClickable` |
| `timeout` | 等超时 | `Timeout` |
| `nav_failed` | 页面打不开 | `NavFailed` |
| `chrome_gone` | Chrome 崩了(会自动重启) | `ChromeGone` |

前四个你自己重试或换个写法;`chrome_gone` 说明容器出事了。

## 5. 并发

**一个容器同时只跑一个动作。** 并发调 `/api/act` 会排队,不会交错 ——
就像 tmux 里两个 client 往同一个 pane 打字,字符是串行进去的。

要真并发?起多个容器。这也是 tmux 的答案:多开几个 session。

```python
browsers = [Browser.start(name=f"w{i}", port=7900+i) for i in range(4)]
```
