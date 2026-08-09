# image_kasmweb — 我们给 kasm 加的那一层真的成立吗

## 这个场景在测什么

`webmuxd/kasmweb-chromium` 是**原厂镜像 + 一个把 CDP 搬出来的中继**。
底座那一半(KasmVNC、6901、`VNC_PW`)我们一个字节没碰,所以这个场景只问三件事:

1. **标签把 profile 说清楚了没有。** 标签是这层 wrapper 的产出物之一,不是注释
   —— 没有它 runtime 就不知道怎么驱动这个镜像。
2. **CDP 真的出来了,而且不用 exec。** 这是这层存在的全部理由:Chromium 只肯听
   容器内 `127.0.0.1`,`docker -p` 是 DNAT 到 eth0,够不着。
3. **窗那一半还是原来的样子** —— 还在听、还要口令。

`host_network=single` 也在这儿断言:KasmVNC 的 `.KasmVNCSock<pid>` 是抽象 socket、
归 netns 管、名字来自 Xvnc 的容器内 PID,共享 netns 的第二个容器必然撞名
(kasmtech/KasmVNC#363)。

## 不在这测什么

- **定位/观测/日志的语义** —— 那些在各自场景里用轻量夹具测过了,这里只验
  "在真镜像上也成立"这一条链路。
- **画面好不好看、卡不卡** —— 测不了,那是人的判断(结论记在 works/08 §4)。

## fixture 来源

`tests/image_conftest.py` 的 `need_image` / `session_on`。
**没有这个镜像就跳过,不是失败** —— 它得 build 出来才有,而 build 一次是 GB 级的事。
