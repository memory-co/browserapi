/**
 * 一个 session 的观看页 —— **把上面那几层接起来,自己不实现任何协议**。
 *
 * 这个文件里没有一行字节操作、没有一个 `WebSocket` 构造、
 * 没有一条丢帧规则 —— 那些分别在 `protocol/`、`channel/`、`flow/` 里,
 * 而那三层能在 node 里单独测
 * ([j §4.1](../../../../docs/v2/works/j-layout.md#41-分层的判据是能不能在-node-里测))。
 *
 * 它剩下的活是**接线**:哪个元素显示画面、哪条通道往哪儿画、状态栏写什么。
 *
 * **它导出一个函数,而不是在模块顶层跑。** 列表页那条路上
 * `main.ts` 根本不调它 —— 于是三条 WebSocket 一条都不连。
 */

import { Api } from "../api.ts";
import { CdpChannel } from "../channel/cdp.ts";
import { RrwebChannel } from "../channel/rrweb.ts";
import { XpraClient } from "../channel/xpra.ts";
import type { Downstream } from "../protocol/messages.ts";
import { pickMode, pickTab, resize } from "../protocol/messages.ts";
import { bindKeyboard } from "../input/keyboard.ts";
import { bindPointer } from "../input/pointer.ts";
import { DomScreen } from "../screen/dom.ts";
import { aligned, effectiveZoom } from "../screen/fit.ts";
import { $, toast } from "./dom.ts";
import { ModeButtons } from "./modes.ts";
import { PendingCards } from "./pending.ts";
import { TabBar } from "./tabs.ts";


/** 接上一个 session:通道、输入、tab 条、状态栏。 */
export function startSessionView(auth: string, base: string): void {

  const api = new Api(auth, base);

  const img = $<HTMLImageElement>("screen");
  const cvs = $<HTMLCanvasElement>("screen2");
  const dom3 = $("screen3");
  const ime = $<HTMLTextAreaElement>("ime");

  // **画面在哪个元素上。** JPG 是 <img>,VNC 是 <canvas>,DOM 是那个容器 ——
  // 除了这一处,下面所有代码对三者一视同仁。
  let screenEl: HTMLElement = img;
  let xpra: XpraClient | null = null;
  let cast = { w: 1024, h: 768 };
  let frameW = 0, frameH = 0;
  let objUrl: string | null = null;
  let frames = 0, bytes = 0;

  // ---------------------------------------------------------------- 画面尺寸

  function setSize(w: number, h: number): void {
    cast = { w, h };
    // **显式定成 CSS 像素**。dsf>1 时帧是 2x 的,不写死会整个画面大一倍
    screenEl.style.width = w + "px";
    screenEl.style.height = h + "px";
    screenEl.classList.remove("dead");
    updateZoom();
  }

  function updateZoom(): void {
    if (!frameW) return;
    const z = effectiveZoom(screenEl.clientWidth, devicePixelRatio, frameW);
    const el = $("s-zoom");
    el.textContent = z.toFixed(2) + "x";
    el.className = aligned(z) ? "" : "bad";
  }

  // **帧的真实尺寸只有解码之后才知道。** CDP 的 metadata 报的是 CSS 尺寸,
  // dsf=2 时它说 1024×768 而图其实是 2048×1536 —— 拿它算"有效缩放"会差一倍,
  // 而那一栏正是用来判断该不该调 dsf 的。
  img.addEventListener("load", () => {
    if (!img.naturalWidth) return;
    frameW = img.naturalWidth;
    frameH = img.naturalHeight;
    $("s-size").textContent = `${frameW}×${frameH}`;
    updateZoom();
  });

  // ---------------------------------------------------------------- 通道

  const cdp = new CdpChannel(api.ws("/channel/cdp"), {
    open() {
      $("s-conn").textContent = "已连接";
      $("s-conn").className = "";
    },
    frame(bytesIn, _frameId) {
      frames++;
      bytes += bytesIn.byteLength;
      const next = URL.createObjectURL(
        new Blob([bytesIn as BlobPart], { type: "image/jpeg" }));
      if (objUrl) URL.revokeObjectURL(objUrl);
      objUrl = next;
      img.src = next;
    },
    message: onMessage,
    close() {
      $("s-conn").textContent = "断开,重连中…";
      $("s-conn").className = "bad";
      screenEl.classList.add("dead");
    },
  });

  const rrweb = new RrwebChannel(api.ws("/channel/rrweb"), (e) => domScreen.feed(e));

  const domScreen = new DomScreen({
    paintbox: $("paintbox"),
    stage: dom3,
    loadReplayer: () => new Promise<void>((res, rej) => {
      const css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = api.asset("/api/rrweb.css");
      document.head.appendChild(css);
      const sc = document.createElement("script");
      sc.src = api.asset("/api/rrweb.js");
      sc.onload = () => res();
      sc.onerror = () => rej(new Error("重放器加载失败"));
      document.head.appendChild(sc);
    }),
    onSize(w, h) { frameW = w; frameH = h; },
    onError(m) {
      $("s-conn").textContent = "DOM 重放器加载失败";
      $("s-conn").className = "bad";
      toast(m + " —— 换 --transport jpg 可以先用", 20000);
    },
  });

  // ---------------------------------------------------------------- 换画面

  const modes = new ModeButtons((name) => cdp.now(pickMode(name)));

  function applyMode(m: { mode: string; label: string; why?: string; available?: never[] }): void {
    const was = modes.current;
    modes.current = m.mode;
    if (m.available) modes.available = m.available;
    modes.render();
    if (was && was !== modes.current) {
      // **切了要说出来。** 画面变了而人不知道为什么,比画面差本身更糟。
      toast("画面换成 " + m.label + (m.why ? `(${m.why})` : ""), 4000);
    }
    // **"显示哪个元素"和"连哪条上游"是两件事,分开写。**
    //
    // 缠在一起过一次:换画面那三行原来只写在 `startXpra()` 里,而它被
    // `if (!xpra)` 挡着。于是 VNC → JPG → VNC 切不回去 —— 第二次点 VNC 时
    // xpra 还连着,`startXpra()` 跳过,那三行也就跟着跳过了。
    // 表现是**按钮点了什么都没发生,而且不报错**,连 console 都是干净的。
    // (`tests/v2_browser_modes/` 现在盯着这条。)
    if (modes.current === "vnc") {
      img.hidden = true; cvs.hidden = false; dom3.hidden = true;
      screenEl = cvs;
      rrweb.close();
      if (!xpra) startXpra();              // 连过一次就不用再连
    } else if (modes.current === "dom") {
      img.hidden = true; cvs.hidden = true; dom3.hidden = false;
      screenEl = dom3;
      $("s-q").textContent = "DOM";
      rrweb.connect();
    } else {
      img.hidden = false; cvs.hidden = true; dom3.hidden = true;
      screenEl = img;
      rrweb.close();                       // 切走了就别占着那条连接
    }
  }

  async function startXpra(): Promise<void> {
    // 显示哪个元素由 `applyMode()` 管 —— 这儿只管把那条连接建起来。
    // 但 `hello` 里 `transport === "vnc"` 那条路会直接调它,所以这三行
    // 得留着(那时还没走过 `applyMode`)。
    img.hidden = true; cvs.hidden = false; dom3.hidden = true;
    screenEl = cvs;
    xpra = new XpraClient(api.ws("/channel/xpra"), cvs, {
      status(st) {
        $("s-conn").textContent = st === "ready" ? "已连接(xpra)"
          : st === "connected" ? "xpra 握手中…" : "xpra " + st;
        $("s-conn").className = (st === "error" || st === "closed") ? "bad" : "";
        if (st === "error" || st === "closed") screenEl.classList.add("dead");
      },
      size(w, h) {
        frameW = w; frameH = h;
        $("s-size").textContent = `${w}×${h}`;
        setSize(w, h);
      },
      log: (m) => toast(m, 12000),
    }).connect();
    $("s-q").textContent = "xpra";
    addEventListener("beforeunload", () => xpra?.close());
  }

  // ---------------------------------------------------------------- 下行

  function onMessage(m: Downstream): void {
    switch (m.type) {
      case "hello": {
        $("ro").hidden = !!m.writable;
        if (m.transport === "vnc" && !xpra) startXpra();
        if (m.transport === "dom") { applyMode({ mode: "dom", label: "DOM" }); }
        modes.current = m.transport || "";
        api.viewModes()
          .then((d) => { modes.available = d.available || []; modes.render(); })
          .catch(() => { /* 拿不到就不显示那排按钮 */ });
        if (m.w) setSize(m.w, m.h!);
        if (!xpra) sendSize();     // xpra 的尺寸是 X 显示定的,问也没用
        return;
      }
      case "cast":
        setSize(m.w, m.h);
        $("s-q").textContent = String(m.quality ?? "");
        cdp.resetTarget();
        return;
      case "quality":
        $("s-q").textContent = m.quality + (m.every_nth > 1 ? " /" + m.every_nth : "");
        return;
      case "mode":
        applyMode(m as never);
        return;
      case "mode_error":
        // **切不动就说清为什么、以及怎么才能有** —— 不静默留在原来那种
        toast(m.message + (m.hint ? " —— " + m.hint : ""), 12000);
        modes.render();            // 把按钮弹回当前那个
        return;
      case "cursor":
        screenEl.style.cursor = m.cursor;   // 服务端已经过白名单
        return;
    }
  }

  // ---------------------------------------------------------------- 输入

  bindPointer([img, cvs, dom3], {
    el: () => screenEl,
    cast: () => cast,
    queue: (m) => cdp.queue(m),
    now: (m) => cdp.now(m),
    focus: () => ime.focus(),
  });
  bindKeyboard(ime, { now: (m) => cdp.now(m) });

  function sendSize(): void {
    const st = $("stage");
    cdp.now(resize(Math.max(320, st.clientWidth - 20),
                   Math.max(240, st.clientHeight - 20)));
  }

  let resizeTimer: ReturnType<typeof setTimeout> | undefined;
  addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(sendSize, 250);
    updateZoom();
  });

  // ---------------------------------------------------------------- tab / 弹窗

  const cards = new PendingCards(api, () => ime.focus());
  const tabs = new TabBar({
    api,
    pick: (id) => { cdp.now(pickTab(id)); cdp.resetTarget(); },
  });

  function events(): void {
    const es = new WebSocket(api.ws("/api/events"));
    es.onmessage = (e) => {
      const m = JSON.parse(e.data as string);
      if (m.type.startsWith("tab.")) tabs.load();
      else if (m.type === "dialog.opened" || m.type === "file.opened") cards.add(m);
      else if (m.type === "dialog.closed" || m.type === "file.closed") cards.drop(m.id);
      else if (m.type === "download.began") toast("下载中 " + m.file);
      else if (m.type === "download.done" && m.state === "done") {
        toast(`下载好了 <a href="${api.downloadUrl(m.id)}" download>${m.file}</a>`, 20000);
      }
    };
    es.onclose = () => setTimeout(events, 2000);
  }

  // ---------------------------------------------------------------- 状态栏

  let xLast = { frames: 0, bytes: 0 };
  setInterval(() => {
    if (xpra) {                    // xpra 的帧不经过 cdp 那条,自己数
      const st = xpra.stats();
      frames = st.frames - xLast.frames;
      bytes = st.bytes - xLast.bytes;
      xLast = { frames: st.frames, bytes: st.bytes };
    }
    $("s-fps").textContent = String(frames);
    $("s-kbps").textContent = String(Math.round(bytes * 8 / 1000));
    frames = 0;
    bytes = 0;
  }, 1000);

  cdp.connect();
  events();
  tabs.load();
  cards.load();
  ime.focus();
}
