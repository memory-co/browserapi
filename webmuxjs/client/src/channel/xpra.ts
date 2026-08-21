/**
 * `/channel/xpra` —— **VNC 那条画面**:连上去、握手、把包画到 canvas 上。
 *
 * 拆包和编码在 `protocol/xpra/`(那两层能在 node 里测);
 * 这个文件是**唯一碰 WebSocket 和 canvas 的一层**。
 *
 * 三条来自实测的硬规矩:
 *
 * - **握手里不报视频编码** —— 于是服务端永远不会发 h264 过来,
 *   我们也就不需要 WebCodecs
 * - **按包序上画** —— `createImageBitmap` 是异步的,并发画会让后来的帧
 *   压在前面的上,滚动时表现为画面撕成两半
 * - **`damage-sequence` 无论成败都要发** —— 它是 xpra 的背压额度,
 *   漏一个就再也收不到帧;和我们自己那条"环 A 无条件回"是同一个道理
 *
 * 键盘鼠标一律不报:它们走 `/channel/cdp`,不走这条。
 */

import { rencode } from "../protocol/xpra/rencode.ts";
import {
  ENCODINGS, Framer, HEADER, MAGIC, ProtocolError, RENCODEPLUS, frame,
  type Packet,
} from "../protocol/xpra/packet.ts";

export interface XpraHandlers {
  status(s: string): void;
  size(w: number, h: number): void;
  log(m: string): void;
}

export class XpraClient {
  url: string;
  canvas: HTMLCanvasElement;
  ctx: CanvasRenderingContext2D;
  on: XpraHandlers;
  ws: WebSocket | null;
  framer: Framer;
  wid: number | null;
  scratch: HTMLCanvasElement | null;
  chain: Promise<void>;
  frames: number;
  bytes: number;
  unknown: Map<string, number>;

  constructor(url: string, canvas: HTMLCanvasElement, opts: Partial<XpraHandlers> = {}) {
    this.url = url;
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { alpha: false })!;
    this.on = Object.assign({ status() {}, size() {}, log() {} }, opts);
    this.ws = null;
    this.framer = new Framer();
    this.wid = null;
    this.scratch = null;       // 画 scroll 用的快照画布
    this.chain = Promise.resolve();   // **按包序上画**,解码是异步的但顺序不能乱
    this.frames = 0; this.bytes = 0;
    this.unknown = new Map();
  }

  connect(): this {
    const ws = new WebSocket(this.url, ["binary"]);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => { this.on.status("connected"); this._hello(); };
    ws.onmessage = (e) => this._feed(new Uint8Array(e.data as ArrayBuffer));
    ws.onclose = () => { this.on.status("closed"); };
    ws.onerror = () => { this.on.status("error"); };
    return this;
  }

  close(): void {
    if (this.ws && this.ws.readyState === 1) {
      this._send(["disconnect", "bye"]);
      this.ws.close();
    }
  }

  // -------------------------------------------------------------- 发(6 种)

  _send(packet: unknown[]): void {
    if (!this.ws || this.ws.readyState !== 1) return;
    // 8 字节头是**大端**,和我们自己那个 28 字节头的小端相反 —— 见 packet.ts
    this.ws.send(frame(rencode(packet)));
  }

  _hello(): void {
    const w = this.canvas.width || 1024, h = this.canvas.height || 768;
    const screen = ["webmuxd", w, h, Math.round(w * 25.4 / 96), Math.round(h * 25.4 / 96),
                    [["webmuxd", 0, 0, w, h, Math.round(w * 25.4 / 96), Math.round(h * 25.4 / 96)]],
                    0, 0, w, h];
    this._send(["hello", {
      "version": "6.6", "client_type": "webmuxd",
      // **每个客户端一个 uuid。** 服务端会把 uuid 相同的旧连接踢掉
      // (sharing.py `drop_older_client`)—— 两个标签页开同一个 session,
      // uuid 撞了就会互相踢。
      "uuid": "webmuxd-" + Math.random().toString(36).slice(2) +
              Math.floor(performance.now()).toString(36),
      "username": "webmuxd",
      // `share` = 我愿意和别人同时看(服务端 `--sharing=yes`,多个观看者各一条流)。
      // `steal` = **必须是 true**:xpra 的检查是
      // `if not steal and _server_sources: 拒绝`,实测**即使我们是唯一的客户端
      // 也会被拒**(它那边一直挂着一个 source)。所有正经的 xpra 客户端默认都是 true。
      "share": true, "steal": true,
      // **不压缩、不加密。** 上行那层白名单靠"level 必须是 0"做第一道判断
      // (view/relay.py),这里保持一致。
      "rencodeplus": true, "lz4": false, "brotli": false, "compression_level": 0,
      "windows": true, "cursors": false, "bell": false, "system_tray": false,
      // **键盘鼠标一律不要。** 它们走我们自己那条通道(works/11 §2.1)。
      "keyboard": false, "mouse.show": false,
      "notifications": { "enabled": false },
      "clipboard": { "enabled": false },
      "audio": { "send": false, "receive": false },
      "file": { "enabled": false },
      "wants": ["packet-types"], "setting-change": true,
      "desktop_size": [w, h], "screen_sizes": [screen],
      "display": { "desktop_size": [w, h], "screen_sizes": [screen] },
      "encodings": {
        "": ENCODINGS, "core": ENCODINGS,
        "rgb_formats": ["RGBX", "RGBA"],
        "window-icon": [], "cursor": [], "packet": true,
      },
      // **不报 full_csc_modes** —— 于是服务端永远不会发视频编码过来,
      // 我们也就不需要 WebCodecs(works/12 §8)。
      "encoding": { "": "auto" },
    }]);
  }

  // -------------------------------------------------------------- 收

  _feed(chunk: Uint8Array): void {
    // 拆包在 protocol/xpra/packet.ts —— 这儿只负责把结果分发出去
    let packets;
    try {
      packets = this.framer.feed(chunk);
    } catch (err) {
      this._fatal(err instanceof ProtocolError ? err.message : String(err));
      return;
    }
    for (const p of packets) this._dispatch(p);
  }

  _fatal(why: string): void {
    this.on.log("xpra 协议错:" + why);
    this.on.status("error");
    if (this.ws) this.ws.close();
  }

  _dispatch(p: Packet): void {
    const t = p[0];
    switch (t) {
      case "hello":
        this.on.log("xpra 服务端 " + (p[1]["version"] || "?") + " · " + (p[1]["server.mode"] || "?"));
        return;
      case "new-window":
      case "new-override-redirect": {
        const [, wid, x, y, w, h] = p;
        // desktop 模式下只会有一个窗口(works/12 §6)。真来了第二个就说出来,
        // **别假装没看见** —— 那说明我们对模式的判断错了。
        if (this.wid !== null && this.wid !== wid) {
          this.on.log("xpra 又开了一个窗口 wid=" + wid + " —— desktop 模式下不该发生");
        }
        this.wid = wid;
        this._resize(w, h);
        this._send(["map-window", wid, x, y, w, h, {}]);
        this._send(["focus", wid, []]);
        return;
      }
      case "window-move-resize":
      case "window-resized":
      case "configure-override-redirect":
        if (p[1] === this.wid && p[4] && p[5]) this._resize(p[4], p[5]);
        return;
      case "draw":
        this._draw(p);
        return;
      case "ping":
        this._send(["ping_echo", p[1], 0, 0, 0, -1]);
        return;
      case "disconnect":
      case "connection-lost":
        this.on.log("xpra 断开:" + (p[1] || ""));
        if (this.ws) this.ws.close();
        return;
      case "startup-complete":
        this.on.status("ready");
        return;
      // **明确不管的。** 列出来而不是让 default 吞掉 —— 这样新出现的包类型
      // 会掉进下面那个计数里,是可见的。
      //
      // `cursor` 值得单说:xpra 这条通道**是活的**,实测悬停在链接和空白之间
      // 切换时它会按变化推送光标图像(24×24 PNG + 热点)。不用它是个决定,
      // 不是漏了 —— 它只存在于这一条来源上,采用它等于同一个行为有两套实现,
      // 而 CDP 探针那条无论如何都得留着(screencast 没有别的选择)。
      // 理由见 docs/v2/works/c-view.md §5.1。
      case "encodings": case "cursor": case "window-metadata":
      case "window-icon": case "lost-window": case "setting-change":
      case "desktop_size": case "bell": case "eos": case "raise-window":
      case "initiate-moveresize": case "pointer-position":
        return;
      default:
        this.unknown.set(t, (this.unknown.get(t) || 0) + 1);
        if (this.unknown.get(t) === 1) this.on.log("xpra 没处理的包:" + t);
    }
  }

  _resize(w: number, h: number): void {
    if (this.canvas.width === w && this.canvas.height === h) return;
    this.canvas.width = w; this.canvas.height = h;
    this.scratch = null;
    this.on.size(w, h);
  }

  // -------------------------------------------------------------- 画

  _draw(p: Packet): void {
    // draw = ["draw", wid, x, y, w, h, coding, 像素, seq, rowstride, options]
    //          0      1    2  3  4  5    6       7     8      9         10
    // **rowstride 在 p[9],不在 options 里。** 拿错了 rgb 帧会整个斜掉。
    const [, wid, x, y, w, h, coding, data, seq, rowstride] = p;
    const opts = p[10] || {};
    this.frames++;
    this.bytes += (data && data.length) || 0;
    const t0 = performance.now();
    // **串起来画。** createImageBitmap 是异步的,并发画会让后来的帧压在前面的上,
    // 滚动时表现为画面撕成两半。
    this.chain = this.chain.then(() => this._paint(coding, x, y, w, h, data, opts, rowstride))
      .catch((err) => { this.on.log("画不出来(" + coding + "):" + err.message); })
      // **ack 无论成败都要发。** 它是 xpra 的背压额度(works/12 §7),
      // 漏一个就再也收不到帧 —— 和我们自己那条"环 A 无条件回"是同一个道理。
      .then(() => this._send(["damage-sequence", seq, wid, w, h,
                              Math.round((performance.now() - t0) * 1000), ""]));
  }

  async _paint(coding: string, x: number, y: number, w: number, h: number,
               data: any, opts: Record<string, any>, rowstride: number): Promise<void> {
    if (coding === "void" || coding === "eos") return;
    if (coding === "scroll") {
      // 新一点的服务端把位移向量放在 options 里,老的放在像素那一格。
      // **两个都不是数组就什么也不做** —— 拿裸字节当位移表去迭代,
      // 会变成一串 NaN 坐标的 drawImage,画面直接花掉。
      const a = opts["scroll"], b = data;
      const moves = Array.isArray(a) ? a : (Array.isArray(b) ? b : null);
      if (!moves) this.on.log("scroll 包里没有位移表,跳过");
      else this._scroll(moves);
      return;
    }
    if (coding.startsWith("rgb")) {
      this.ctx.putImageData(this._rgb(data, w, h, opts, rowstride), x, y);
      return;
    }
    const type = "image/" + coding.split("/")[0];
    const bmp = await createImageBitmap(new Blob([data], { type }));
    this.ctx.drawImage(bmp, x, y);
    bmp.close();
  }

  // `scroll` 就是把画布上已有的像素挪个位置 —— **零字节、零解码**(works/12 §3)。
  // 必须先拍快照再搬:直接在同一块画布上重叠自搬会拖出残影。
  _scroll(moves: number[][]): void {
    if (!moves || !moves.length) return;
    const c = this.canvas;
    if (!this.scratch) {
      this.scratch = document.createElement("canvas");
      this.scratch.width = c.width; this.scratch.height = c.height;
    }
    const sc = this.scratch.getContext("2d")!;
    sc.drawImage(c, 0, 0);
    for (const m of moves) {
      // 六个数缺一不可 —— 少一个就是一串 NaN 坐标的 drawImage,画面直接花掉
      if (!m || m.length < 6) continue;
      const [sx, sy, sw, sh, dx, dy] = m as [number, number, number, number, number, number];
      this.ctx.drawImage(this.scratch, sx, sy, sw, sh, sx + dx, sy + dy, sw, sh);
    }
  }

  _rgb(data: Uint8Array, w: number, h: number, opts: Record<string, any>,
       rowstride: number): ImageData {
    const fmt = opts["rgb_format"] || "RGBX";
    const px = new Uint8ClampedArray(w * h * 4);
    const stride = rowstride || Math.floor(data.length / h);
    const bpp = fmt.length === 4 ? 4 : 3;
    // 通道次序按服务端说的来,**不猜**。RGBX/BGRX 没有 alpha,补成不透明。
    const r = fmt.indexOf("R"), g = fmt.indexOf("G"), b = fmt.indexOf("B");
    const a = fmt.indexOf("A");
    for (let row = 0; row < h; row++) {
      let s = row * stride, d = row * w * 4;
      for (let i = 0; i < w; i++, s += bpp, d += 4) {
        px[d] = data[s + r]!; px[d + 1] = data[s + g]!; px[d + 2] = data[s + b]!;
        px[d + 3] = a >= 0 ? data[s + a]! : 255;
      }
    }
    return new ImageData(px, w, h);
  }

  stats(): { frames: number; bytes: number; unknown: Record<string, number> } {
    return { frames: this.frames, bytes: this.bytes,
             unknown: Object.fromEntries(this.unknown) };
  }
}
