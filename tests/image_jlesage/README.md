# image_jlesage — 这层 wrapper 几乎什么都没加,那它到底加了什么

## 这个场景在测什么

和 [`image_kasmweb/`](../image_kasmweb/) 是**同一份代码驱动两个完全不同的镜像**,
所以这个场景专门测**不一样的地方**:

1. **标签的值都不同** —— 5800/http、`WEB_AUTHENTICATION_PASSWORD`、
   `CHROMIUM_CUSTOM_ARGS`、登录名是变量定的而不是写死的。
2. **中继是底座自己的。** 它内置了 socat 转发,只是默认关着 —— wrapper 的全部
   内容就是"把它打开"。所以断言跑着的是 `socat`,**而且没有**我们那个 `cdp-relay.py`。
3. **两个容器能共享 host netns。** 这是它比 kasm 强的那一点,也是选它的唯一理由:
   共享 netns 正是"容器里的 localhost 就是宿主机的 localhost"的前提。

## 不在这测什么

- **它和 kasm 哪个画面好** —— 人的判断,不是断言(结论:KasmVNC 更好,works/08 §4)。
- **host 网络下 kasm 为什么不行** —— 那是 kasm 的事实,记在 works/08 §6.2;
  这里只正面证明这个镜像可以。

## fixture 来源

`tests/image_conftest.py`。最后那条会真起两个共享 host netns 的容器,**慢**,
标了 `slow`。
