/**
 * DOM 那条画面 —— **rrweb 重放,只读。**
 *
 * 重放出来的那棵 DOM 整个 `pointer-events: none` ——
 * **点不到、选不中、链接也点不开**,事件全落在外面那个容器上,
 * 再走 `/channel/cdp` 翻译成 `Input.*`。
 * **只读是结构性的,不是靠自觉**([c §7](../../../../docs/v2/works/c-view.md#7-接缝切在哪))。
 */

import { replayScale } from "./fit.ts";

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
      this.fit();
      return;
    }

    try { this.replayer.addEvent(e); } catch { /* 单条坏事件不该毁掉整条流 */ }
  }

  fit(): void {
    const wrap = this.d.paintbox.querySelector(".replayer-wrapper") as HTMLElement | null;
    if (!wrap) return;
    const w = this.d.stage.getBoundingClientRect().width;
    if (w) wrap.style.transform = `scale(${replayScale(w, this.frameW)})`;
  }
}
