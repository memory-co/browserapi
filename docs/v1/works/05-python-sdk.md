# 05 · Python lib 模式

## 1. 设计立场

**lib 是 service 的瘦客户端。** 两种模式共用同一份 schema 与同一条执行路径,
`local` 模式只是把"HTTP 调用 remote 控制面"换成"进程内调用嵌入式控制面"。
这样"本地能跑、线上不行"这类问题从结构上被消除。

三层 API,让不同深度的使用者各取所需:

| 层 | 面向 | 特征 |
| --- | --- | --- |
| **L1 脚本层** | 写自动化脚本的人 | `s.click("提交订单")`,语义定位,像 Playwright |
| **L2 Agent 层** | 写 Agent 循环的人 | `s.observe()` → 元素表 + 标注图,`run/step` 上下文 |
| **L3 协议层** | 框架集成者 | 直接收发 Action/Observation dataclass,自己控制批量与并发 |

## 2. 安装与连接

```python
pip install browserapi            # 纯客户端
pip install browserapi[local]     # 额外带嵌入式控制面(docker SDK + sqlite)
```

```python
from browserapi import Browser

# 形态 A:本地 —— 自动拉起 operator 容器,轨迹落 ./.bapi/
bapi = Browser.local(image="browserapi/operator:1.0", runs_dir="./.bapi")

# 形态 B/C:远端服务
bapi = Browser.connect("https://bapi.internal", api_key=os.environ["BAPI_KEY"])

# 二选一由环境决定,代码不变
bapi = Browser.auto()   # 有 BAPI_ENDPOINT 就 connect,否则 local
```

## 3. L1:脚本层

```python
with bapi.session(profile="shop-account-1", viewport=(1280, 800)) as s:
    print(s.live_url)          # 把这个链接发给同事,他能实时看到这个浏览器

    s.goto("https://shop.example.com")
    s.click(text="登录")
    s.type(label="手机号", text="13800000000")
    s.type(label="密码", text_ref="secret://vault/shop/pwd")   # 凭证不落轨迹
    s.click(role="button", name="登录")
    s.wait_for(url_contains="/home")

    items = s.extract(selector=".cart-item", mode="table")
    s.screenshot("cart.png")
```

定位参数是 [03 §3](03-action-protocol.md) `Target` 的语法糖:

| 写法 | 展开为 |
| --- | --- |
| `s.click("提交订单")` | `{kind: semantic, name: "提交订单"}` |
| `s.click(role="button", name="登录")` | `{kind: semantic, role, name}` |
| `s.click(el)`(`el` 来自 `observe()`) | `{kind: element_id, ...}` |
| `s.click(sig="sig_7c1e...")` | `{kind: signature}` |
| `s.click(selector="#pay")` | `{kind: selector}` |
| `s.click(at=(890, 632))` | `{kind: point}` |

## 4. L2:Agent 层

这一层是本 SDK 的重点,直接服务"操作路径可见"。

```python
with bapi.session() as s, s.run(
        goal="预订 8/20 北京→上海上午经济舱",
        agent={"name": "travel-agent", "version": "v3.2.1", "model": "claude-opus-5"},
        labels={"env": "prod"}) as run:

    print(run.live_url)        # 直播:左边浏览器画面,右边它的每一步

    while not run.finished:
        obs = s.observe()                       # 标注截图 + 元素表

        decision = my_llm(                      # ← 你的大脑,browserapi 不掺和
            goal=run.goal,
            image=obs.screenshot.png,           # 已带 Set-of-Mark 编号
            elements=obs.elements.as_prompt(),  # 紧凑文本,直接进 prompt
            history=run.history(last=5),        # 前几步的动作与结果摘要
        )

        with run.step(observation=obs,
                      thought=decision.thought,
                      plan=decision.plan) as step:      # ← 思考进轨迹
            for a in decision.actions:
                r = step.act(a)                          # 执行 + 自动记录 effect
                if not r.ok:
                    step.note(f"执行失败:{r.status}")
                    break

    print(run.outcome)         # done / failed + 归因
    print(run.replay_url)      # 事后回放链接
```

要点:
- `run.step(...)` 是上下文管理器。**退出时同步 flush**([04 §8](04-trajectory-model.md)),
  异常也会被捕获记入 `step.status` 后再抛出——不会因为你的代码炸了就丢掉这一步的记录。
- `obs.elements.as_prompt()` 输出的是给模型的紧凑表示:
  ```
  [12] button "提交订单"        (视口内)
  [13] textbox "优惠码" = ""
  [14] link   "返回购物车"      (需下滑)
  ```
- `run.history(last=n)` 给的是**动作与效果摘要**,不是原始 JSON,直接可进 prompt。
- 不提供 `run.think()` 之类的 LLM 封装——[00 §3](00-goals-and-scope.md) 非目标。

### 4.1 与主流 Agent 框架对接
提供适配器,把 browserapi 的动作空间导出成各框架的 tool schema:

```python
from browserapi.integrations import as_tools

tools = as_tools(session, dialect="anthropic")   # 也支持 openai / langchain / mcp
# 每个 tool 调用自动落轨迹,thought 从模型的 reasoning 字段自动填充(若有)
```
这样"操作路径可见"对框架用户是**零改造**获得的。

## 5. L3:协议层

```python
from browserapi.types import Action, Target

results = s.dispatch([
    Action.click(Target.element(obs, 12)),
    Action.type(Target.element(obs, 13), text="SAVE20"),
    Action.press_key("Enter"),
])   # 串行执行、遇错即停,一次往返
```

## 6. 错误模型

对应 [03 §5](03-action-protocol.md) 的二分:

```python
from browserapi.errors import ActionError, PlatformError

try:
    s.click("提交订单")
except ActionError as e:        # 可自愈:target_not_found / not_actionable / timeout / denied
    print(e.status, e.candidates)   # 附带最接近的候选元素,便于纠正或反馈给模型
except PlatformError as e:      # 平台问题:page_crashed / session_gone / internal
    alert(e)                        # 不该让 Agent 盲目重试
```

`ActionError.candidates` 是刻意设计的:定位失败时把"最像的三个元素"塞回异常里,
使得"点错了"这件事在代码里、在轨迹里、在回放器里是同一份信息。

## 7. 并发

```python
with bapi.pool(size=8) as pool:                 # 8 个 operator 容器
    results = pool.map(handle_one, tasks)       # 每个任务独占一个会话
```
- 会话**不是线程安全**的:一个 `Session` 同时只能有一个执行者。SDK 内部加锁并在违规时直接报错,
  而不是产生难以复现的交错。
- `pool` 负责容器复用:任务结束后 `reset()`(清 cookie / 关多余标签 / 回 about:blank)而非销毁,
  省掉冷启动;`profile` 不同则不复用。

## 8. 同步与异步

同步 API 为主(脚本与 Agent 循环绝大多数是同步的),异步镜像 API 命名前缀 `Async`:
```python
async with await AsyncBrowser.connect(...) as bapi: ...
```
两套由同一份 schema 生成,行为一致。**不做 sync-over-async 的假同步**——那会在事件循环里踩坑。
