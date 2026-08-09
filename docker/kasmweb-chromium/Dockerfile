# webmuxd/kasmweb-chromium —— kasm 原厂镜像 + 一个把 CDP 搬出来的中继。
#
# **只加一层,不改底座的任何脚本。** 窗那一半原样是 kasm 的
# (KasmVNC,6901 自签名 https,VNC_PW 定口令),我们只补上 webmuxd 需要的
# 第二个端点:一个 `-p` 够得着的 CDP 口。
#
#   docker build -t webmuxd/kasmweb-chromium:1.18.0 docker/kasmweb-chromium/
#
# **host 网络下这个镜像一台机器只能跑一个。** KasmVNC 用
# `.KasmVNCSock<pid>` 这个抽象 unix socket 做内部会合点,而抽象 socket 归
# network namespace 管、名字来自 Xvnc 的容器内 PID —— 共享 netns 的第二个
# 容器必然撞名(kasmtech/KasmVNC#363)。要一机多开就别用 --network host。
ARG BASE=kasmweb/chromium:1.18.0
FROM ${BASE}

USER root
COPY cdp-relay.py  /usr/local/bin/cdp-relay.py
COPY entrypoint.sh /usr/local/bin/webmuxd-entrypoint
RUN chmod 755 /usr/local/bin/webmuxd-entrypoint /usr/local/bin/cdp-relay.py

# kasm 的启动脚本**死等一张叫 `eth*` 的网卡**:
#     for interface in $interfaces; do
#         if [[ $interface == eth* ... ]]; then return; fi
#     done
#     sleep 1        # 认不出就永远转下去
# bridge 下 docker 正好把网卡叫 eth0,所以这行从来没暴露过;`--network host`
# 下容器看到的是宿主机的真实网卡(ens4 / enp0s3 …,现代 Linux 基本都不叫
# eth0),于是 Xvnc 和 Chromium 一个都起不来 —— 而症状是"容器 Up、日志停住、
# 没有任何报错"。
#
# **改在我们这一层,底座镜像本身不动。** 补丁打不上就让 build 失败,
# 绝不静默留一份没改的(那会在运行时卡死,报错还指向别处)。
RUN grep -q 'function wait_for_network_devices() {' /dockerstartup/vnc_startup.sh \
 && sed -i 's|function wait_for_network_devices() {|&\n\treturn 0  # webmuxd: 宿主机网卡不叫 eth*|' \
        /dockerstartup/vnc_startup.sh
USER 1000

ENV WEBMUXD_CDP_PORT=9222
EXPOSE 6901 9222

# 这些标签就是 works/08 §5 那张 profile 表,**做成机器可读的** ——
# 接一个新镜像不用改 webmuxd 的代码,`docker inspect` 就知道它长什么样。
LABEL webmuxd.window.port=6901 \
      webmuxd.window.scheme=https \
      webmuxd.window.user=kasm_user \
      webmuxd.window.password_env=VNC_PW \
      webmuxd.window.port_env=NO_VNC_PORT \
      webmuxd.cdp.port=9222 \
      webmuxd.cdp.port_env=WEBMUXD_CDP_PORT \
      webmuxd.chromium.args_env=APP_ARGS \
      webmuxd.chromium.url_env=LAUNCH_URL \
      webmuxd.host_network=single

ENTRYPOINT ["/usr/local/bin/webmuxd-entrypoint"]
CMD ["--wait"]
