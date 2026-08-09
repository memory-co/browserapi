"""把 Chromium 的调试口搬到一个 `-p` 够得着的地址。

Chromium 把调试端口绑死在容器内的 127.0.0.1 上,而 `docker -p` 是 DNAT 到容器的
eth0 —— 那上面没人听,所以直接映射是个死口(webmuxd works/08 §3)。

这段就监听 0.0.0.0:<对外口>,转发到 127.0.0.1:<Chromium 那个口>。纯字节对拷,
不解析任何协议。

    python3 cdp-relay.py <对外口> <Chromium 口>
"""

import asyncio
import sys


async def pipe(reader, writer):
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(client_r, client_w, target_port):
    # **每条连接才去连一次**,不预连 —— 这样 Chromium 起得比中继晚也没关系,
    # 它起来之后下一条连接自然就通了。
    try:
        server_r, server_w = await asyncio.open_connection("127.0.0.1", target_port)
    except Exception:
        client_w.close()
        return
    await asyncio.gather(pipe(client_r, server_w), pipe(server_r, client_w))


async def main(listen_port, target_port):
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, target_port), "0.0.0.0", listen_port)
    print(f"cdp-relay: 0.0.0.0:{listen_port} -> 127.0.0.1:{target_port}", flush=True)
    await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]), int(sys.argv[2])))
