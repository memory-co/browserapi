/**
 * 换画面那块 —— **贴在画面右下角,像视频播放器的画质菜单。**
 *
 * 收起来的时候只是一小块半透明的牌子,写着现在是哪一种;点一下往上弹出另外几种。
 * 为什么不是顶栏里一排按钮:**后面要做全屏**,那时所有控制层都得和主屏融合,
 * 顶栏没地方待。现在就放对位置,省得到时候搬。
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
  private open = false;

  constructor(private pick: (name: string) => void) {
    // **点别处就收起来。** 菜单开着不收,它会挡住画面右下角那一块 ——
    // 而那儿常常正是页面的内容。
    addEventListener("pointerdown", (e) => {
      if (!this.open) return;
      if (!$("quality").contains(e.target as Node)) this.toggle(false);
    }, true);
    addEventListener("keydown", (e) => {
      if (this.open && e.key === "Escape") { this.toggle(false); $("q-now").focus(); }
    });
  }

  private toggle(open: boolean): void {
    this.open = open;
    $("quality").classList.toggle("open", open);
    $("q-list").hidden = !open;
    $("q-now").setAttribute("aria-expanded", String(open));
  }

  render(): void {
    const box = $("quality");
    // 只有一种可选就整块不画 —— **画一个点不了的东西比不画更让人困惑**
    if (this.available.length < 2) { box.hidden = true; this.toggle(false); return; }
    box.hidden = false;

    const now = this.available.find((m) => m.name === this.current);
    $("q-now").textContent = now ? now.label : this.current.toUpperCase();
    $("q-now").setAttribute("title", now ? `${now.blurb} —— ${now.when}` : "换画面");
    $("q-now").onclick = () => this.toggle(!this.open);

    const list = $("q-list");
    list.innerHTML = this.available.map((m) =>
      `<li role="option" tabindex="0" data-mode="${m.name}"` +
      ` aria-selected="${m.name === this.current}"` +
      ` title="${m.when}">${m.label}<small>${m.blurb}</small></li>`,
    ).join("");
    for (const li of list.querySelectorAll<HTMLLIElement>("li")) {
      const choose = () => {
        this.toggle(false);
        if (li.dataset.mode && li.dataset.mode !== this.current) this.pick(li.dataset.mode);
      };
      li.onclick = choose;
      // 键盘也能选 —— 这块是浮层,不能只认鼠标
      li.onkeydown = (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(); }
      };
    }
  }
}
