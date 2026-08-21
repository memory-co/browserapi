/**
 * 那排换画面的按钮。
 *
 * **使用者看到的是 JPG / VNC / DOM** —— `screencast` / `xpra` / `rrweb`
 * 是实现名,不上界面([c §9.1](../../../../docs/v2/works/c-view.md#91-使用者看到的是三个词))。
 * 界面上那几个字全部来自 `/api/view/mode`,**这儿不自己写一遍**。
 */

import { $ } from "./dom.ts";

export interface ModeChoice {
  name: string; label: string; blurb: string; when: string;
}

export class ModeButtons {
  current = "";
  available: ModeChoice[] = [];

  constructor(private pick: (name: string) => void) {}

  render(): void {
    const box = $("modes");
    // 只有一种就别占地方
    if (this.available.length < 2) { box.innerHTML = ""; return; }
    box.innerHTML = this.available.map((m) =>
      `<button class="mode${m.name === this.current ? " on" : ""}"` +
      ` data-mode="${m.name}" title="${m.blurb} —— ${m.when}">${m.label}</button>`,
    ).join("");
    for (const b of box.querySelectorAll<HTMLButtonElement>("button")) {
      b.onclick = () => {
        if (b.dataset.mode && b.dataset.mode !== this.current) this.pick(b.dataset.mode);
      };
    }
  }
}
