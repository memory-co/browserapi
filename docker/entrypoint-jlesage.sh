#!/bin/sh
# webmuxd wrapper —— 这个底座**本来就有**我们要的东西:一个内置的 socat 服务,
# 把 Chromium 那个只绑 loopback 的调试口搬到 0.0.0.0。
#
# 所以 wrapper 几乎什么都不做,只把它默认打开(`ENV CHROMIUM_REMOTE_DEBUGGING=1`,
# 在 Dockerfile 里)。
#
# **端口用它自己的变量名 `CHROMIUM_REMOTE_DEBUGGING_PORT`,我们不另起一个。**
# 试过用 `WEBMUXD_CDP_PORT` 做别名,做不到:s6 起服务时按镜像 env 重建环境,
# entrypoint 里 export 传不下去;而 `/etc/cont-env.d/` 只提供**默认值**,
# 底座的镜像 ENV 已经定义了这个变量,默认值就被盖住了。
#
# 与其造一个盖不住的别名,不如让**标签**去表达统一性:
# `webmuxd.cdp.port_env` 写明这个镜像该设哪个变量,调用方读标签就知道。
exec /init "$@"
