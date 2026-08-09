# webmuxd/jlesage-chromium —— jlesage 原厂镜像 + 默认打开它自带的 CDP 转发。
#
# 这个底座**本来就做了**我们要的事:内置一个 socat 服务把 Chromium 那个只绑
# loopback 的调试口搬到 0.0.0.0。wrapper 只是把它默认打开,并把端口的名字
# 统一成 `WEBMUXD_CDP_PORT`,好让两个镜像对外长得一样。
#
#   docker build -t webmuxd/jlesage-chromium:latest -f docker/jlesage-chromium.Dockerfile docker/
#
# **这个镜像能用 --network host 一机多开。** 它给 Xvnc 的是
# `-nolisten local -rfbport=-1 -rfbunixpath=...` —— X 和 RFB 都走文件系统上的
# socket,抽象命名空间里一个带名字的都没有,所以共享 netns 不会撞。
ARG BASE=jlesage/chromium:latest
FROM ${BASE}

COPY entrypoint-jlesage.sh /usr/local/bin/webmuxd-entrypoint
RUN chmod 755 /usr/local/bin/webmuxd-entrypoint

# 默认打开底座自带的 CDP 转发。端口沿用它自己的变量名,理由见 entrypoint。
ENV CHROMIUM_REMOTE_DEBUGGING=1
EXPOSE 5800 9222

LABEL webmuxd.window.port=5800 \
      webmuxd.window.scheme=http \
      webmuxd.window.user_env=WEB_AUTHENTICATION_USERNAME \
      webmuxd.window.password_env=WEB_AUTHENTICATION_PASSWORD \
      webmuxd.window.port_env=WEB_LISTENING_PORT \
      webmuxd.cdp.port=9222 \
      webmuxd.cdp.port_env=CHROMIUM_REMOTE_DEBUGGING_PORT \
      webmuxd.chromium.args_env=CHROMIUM_CUSTOM_ARGS \
      webmuxd.chromium.url_env=CHROMIUM_APP_URL \
      webmuxd.host_network=multi

ENTRYPOINT ["/usr/local/bin/webmuxd-entrypoint"]
