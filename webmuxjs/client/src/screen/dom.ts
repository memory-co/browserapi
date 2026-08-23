/**
 * DOM 那条画面 —— **rrweb 重放,只读。**
 *
 * 重放出来的那棵 DOM 整个 `pointer-events: none` ——
 * **点不到、选不中、链接也点不开**,事件全落在外面那个容器上,
 * 再走 `/channel/cdp` 翻译成 `Input.*`。
 * **只读是结构性的,不是靠自觉**([c §7](../../../../docs/v2/works/c-view.md#7-接缝切在哪))。
 */

import { replayScale } from "./fit.ts";

//: 建完重放器之后按帧复查多少帧。实测那个 iframe 在 **3 秒多**之后才被造出来,
//: 造出来之后 rrweb 还会 `document.write` 换一次根 —— 两下都得抓到。
//: 10 秒够了;复查一次只是一个 `querySelector`。
const RESEAL_FRAMES = 600;

declare const rrweb: any;

export interface DomScreenDeps {
  /** 重放器画在哪 —— **只清这个容器,别动兄弟节点**(对话框卡片是它的兄弟)。 */
  paintbox: HTMLElement;
  /** 外面那个接事件的容器。 */
  stage: HTMLElement;
  /** 加载重放器(`/api/rrweb.js` + `.css`)。 */
  loadReplayer(): Promise<void>;
  onSize(w: number, h: number): void;
  onError(message: string): void;
}

export class DomScreen {
  private replayer: any = null;
  private pending: any[] = [];
  private loaded: Promise<void> | null = null;
  private frameW = 0;
  /** 已经钉住的那个根元素。**认根元素,不认 `Document`** ——
   *  rrweb 是 `document.write` 重建的:`Document` 对象一直是同一个,
   *  而 `documentElement` 被整个换掉。按文档去重就会漏掉换根那一次,
   *  于是 `inert` 设在了一棵马上要被丢掉的树上。 */
  private sealedRoot: Element | null = null;
  private watching: MutationObserver | null = null;

  constructor(private d: DomScreenDeps) {
    addEventListener("resize", () => this.fit());
  }

  private ready(): Promise<void> {
    if (!this.loaded) {
      this.loaded = this.d.loadReplayer().catch((err: Error) => {
        // **不静默换一种。** 选了 DOM 而它起不来是个要修的事,
        // 不是该被悄悄绕过去的事。
        this.d.onError("DOM 重放器加载失败:" + err.message);
        throw err;
      });
    }
    return this.loaded;
  }

  async feed(e: any): Promise<void> {
    try { await this.ready(); } catch { return; }

    if (e.type === 4) {                     // Meta:新的一页,推倒重来
      if (this.replayer) {
        try { this.replayer.destroy(); } catch { /* 已经没了就算了 */ }
        this.replayer = null;
      }
      this.d.paintbox.innerHTML = "";
      this.pending = [e];
      if (e.data?.width) {
        this.frameW = e.data.width;
        this.d.onSize(e.data.width, e.data.height);
      }
      return;
    }

    if (!this.replayer) {
      this.pending.push(e);
      if (e.type !== 2) return;             // 等到全量快照才建得起来
      this.replayer = new rrweb.Replayer(this.pending, {
        root: this.d.paintbox, liveMode: true, mouseTail: false,
        UNSAFE_replayCanvas: true, insertStyleRules: [],
      });
      // **基线取"现在",不是快照的时间戳。** live 模式按 `事件时间 − 基线`
      // 排期;基线取十秒前那张快照的话,后面每条新事件都被排到十秒后才应用 ——
      // 表现是"点了没反应",而且不报错。
      this.replayer.startLive(Date.now());
      this.pending = [];
      this.watchSeal();
      this.fit();
      return;
    }

    // **每条事件应用之前也确认一次。** 观察者是主路,这是兜底 ——
    // 而且必须在 `addEvent` **之前**:夺焦点的正是被应用的那条 focus 事件。
    this.seal();
    try { this.replayer.addEvent(e); } catch { /* 单条坏事件不该毁掉整条流 */ }
  }

  /**
   * **把重放那棵树钉成拿不走焦点的。**
   *
   * `pointer-events: none` 只挡住鼠标。**焦点是另一条路**:rrweb 会把录下来的
   * focus 事件放出来(百度一加载就 focus 搜索框),它在 iframe 里调 `.focus()`,
   * 于是**观看端的键盘焦点整个跑进那个 iframe** —— 人再敲什么都进了那棵
   * 只读的树,一个字都到不了服务端,而且**一条错都不报**。
   *
   * `inert` 挡得住,但**必须设在 iframe 自己的文档里** —— 设在外面那个容器上
   * 跨不进去(试过,焦点照样被夺)。
   *
   * 每换一棵树重设一次:那个 iframe 是 rrweb 造的,`type === 4` 那儿
   * 整棵推倒重来之后是新的一个。
   */
  /**
   * **把重放那棵树钉成拿不走焦点的。**
   *
   * `pointer-events: none` 只挡住鼠标。**焦点是另一条路**:rrweb 会把录下来的
   * focus 事件放出来(百度一加载就 focus 搜索框),它在 iframe 里调 `.focus()`,
   * 于是**观看端的键盘焦点整个跑进那个 iframe** —— 人再敲什么都进了那棵
   * 只读的树,一个字都到不了服务端,而且**一条错都不报**。
   *
   * `inert` 挡得住,但**必须设在 iframe 自己的文档里** —— 设在外面那个容器上
   * 跨不进去(试过,焦点照样被夺)。
   *
   * 用 `MutationObserver` 等那个 iframe 出现,**不靠重试几次**:
   * 实测它在建完重放器之后 **3 秒多**才被造出来,而页面一静下来就再没有
   * 事件进来 —— 拿帧数或者事件当时机,一张不动的页上永远钉不上,
   * 而那正是人最想打字的时候。
   */
  private watchSeal(): void {
    this.watching?.disconnect();
    this.watching = new MutationObserver(() => this.seal());
    this.watching.observe(this.d.paintbox, { childList: true, subtree: true });
    this.sealedRoot = null;
    this.recheck(RESEAL_FRAMES);            // 换根那一下不产生 paintbox 变化
  }

  /** 按帧复查一小段。**观察者看不到 iframe 里面换根**,而那正是要抓的一下。 */
  private recheck(left: number): void {
    this.seal();
    if (left > 0) requestAnimationFrame(() => this.recheck(left - 1));
  }

  private seal(): void {
    try {
      const ifr = this.d.paintbox.querySelector("iframe") as HTMLIFrameElement | null;
      const root = ifr?.contentDocument?.documentElement ?? null;
      if (!root || root === this.sealedRoot) return;
      (root as HTMLElement).inert = true;
      this.sealedRoot = root;               // 换了根就会重新钉
    } catch { /* 拿不到就算了 —— 只读还有 pointer-events 那一道 */ }
  }

  fit(): void {
    const wrap = this.d.paintbox.querySelector(".replayer-wrapper") as HTMLElement | null;
    if (!wrap) return;
    const w = this.d.stage.getBoundingClientRect().width;
    if (w) wrap.style.transform = `scale(${replayScale(w, this.frameW)})`;
  }
}
