/**
 * 挡着页面的那些 —— **对话框和文件选择要画出来**。
 *
 * headless 里它们根本不渲染;不画的话人遇到的是"点了没反应"
 * ([g](../../../../docs/v2/works/g-native-ui.md))。
 *
 * 数据来自 `/api/pending` 和 `/api/events`,**和上层自己画用的是同一组接口**。
 */

import type { Api, Pending } from "../api.ts";
import { $ } from "./dom.ts";

export class PendingCards {
  private queue: Pending[] = [];

  constructor(private api: Api, private refocus: () => void) {}

  async load(): Promise<void> {
    try {
      const p = await this.api.pending();
      this.queue = [...(p.dialogs || []), ...(p.file_choosers || [])];
      this.show();
    } catch { /* 拉不到就等事件推 */ }
  }

  add(it: Pending): void {
    this.queue.push(it);
    if (this.queue.length === 1) this.show();
  }

  /** 别人回填了、或者超时了 —— 把这边那张卡撤掉。 */
  drop(id: string): void {
    const n = this.queue.length;
    this.queue = this.queue.filter((q) => q.id !== id);
    if (this.queue.length !== n) this.show();
  }

  private show(): void {
    const modal = $("modal"), card = $("card");
    const it = this.queue[0];
    if (!it) { modal.classList.remove("on"); this.refocus(); return; }
    modal.classList.add("on");
    if (it.kind === "dialog") this.dialog(card, it);
    else if (it.kind === "file") this.files(card, it);
  }

  private next(): void {
    this.queue.shift();
    this.show();
  }

  private dialog(card: HTMLElement, it: Pending): void {
    const isPrompt = it.subtype === "prompt";
    card.innerHTML = `<h3>页面弹了一个 ${it.subtype}</h3><p></p>` +
      (isPrompt ? `<input type=text id=dtext>` : "") +
      `<div class=row>${it.subtype === "alert" ? "" : "<button id=no>取消</button>"}
       <button class=go id=yes>确定</button></div>`;
    // **textContent** —— 弹窗文本是页面给的
    card.querySelector("p")!.textContent = it.text || "";
    if (isPrompt) {
      const i = card.querySelector<HTMLInputElement>("#dtext")!;
      i.value = it.default || "";
      i.focus();
    }
    const answer = (accept: boolean) => {
      this.api.answerDialog(it.tab!, accept,
        isPrompt ? card.querySelector<HTMLInputElement>("#dtext")!.value : "");
      this.next();
    };
    card.querySelector<HTMLElement>("#yes")!.onclick = () => answer(true);
    const no = card.querySelector<HTMLElement>("#no");
    if (no) no.onclick = () => answer(false);
  }

  private files(card: HTMLElement, it: Pending): void {
    card.innerHTML = `<h3>页面要选文件</h3><p>选一个传上去,或者取消。</p>
      <input type=file id=fpick ${it.mode === "selectMultiple" ? "multiple" : ""}>
      <div class=row><button id=fno>取消</button>
      <button class=go id=fyes>用它</button></div>`;
    const done = (names: string[]) => {
      this.api.answerFiles(it.id, names);
      this.next();
    };
    card.querySelector<HTMLElement>("#fno")!.onclick = () => done([]);
    card.querySelector<HTMLElement>("#fyes")!.onclick = async () => {
      const picked = [...card.querySelector<HTMLInputElement>("#fpick")!.files ?? []];
      const names: string[] = [];
      for (const f of picked) names.push(...await this.api.upload(f));
      done(names);
    };
  }
}
