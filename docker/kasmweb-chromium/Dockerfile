# 把 kasmweb/chromium 改造成 webmuxd 能用的镜像:补 CDP 端点,
# 并让它在 --network host 下起得来。细节和代价见 ./README.md。
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
        /dockerstartup/vnc_startup.sh \
 && grep -q -- '-interface 0.0.0.0' /dockerstartup/vnc_startup.sh \
 && sed -i 's|-interface 0.0.0.0|-interface ${KASM_INTERFACE:-0.0.0.0}|g' \
        /dockerstartup/vnc_startup.sh
USER 1000

ENV WEBMUXD_CDP_PORT=9222
EXPOSE 6901 9222

# 这些标签就是 works/08 §5 那张 profile 表,**做成机器可读的** ——
# 接一个新镜像不用改 webmuxd 的代码,`docker inspect` 就知道它长什么样。
LABEL webmuxd.window.port=6901 \
      webmuxd.window.scheme=https \
      webmuxd.window.user=kasm_user \
      webmuxd.window.password_env=WEBMUXD_PASSWORD \
      webmuxd.window.port_env=WEBMUXD_WINDOW_PORT \
      webmuxd.window.bind_env=WEBMUXD_BIND \
      webmuxd.cdp.port=9222 \
      webmuxd.cdp.port_env=WEBMUXD_CDP_PORT \
      webmuxd.chromium.args_env=APP_ARGS \
      webmuxd.chromium.url_env=LAUNCH_URL \
      webmuxd.host_network=single

ENTRYPOINT ["/usr/local/bin/webmuxd-entrypoint"]
CMD ["--wait"]
