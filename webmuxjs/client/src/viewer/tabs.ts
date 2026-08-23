/**
 * 那条外挂的 tab 条 —— **数据全部来自 `/api/tabs` 和 `/api/events`**,
 * 和上层自己画用的是同一组接口([f](../../../../docs/v2/works/f-tabs.md))。
 */

import type { Api, TabInfo } from "../api.ts";
import { $ } from "./dom.ts";

export interface TabBarDeps {
  api: Api;
  /** 切 tab 走上行消息,不走 HTTP —— 它要和画面同一条路,否则会错序。 */
  pick(id: string): void;
}

export class TabBar {
  tabs: TabInfo[] = [];
  active: string | null = null;
  /** 每个 tab 打了一半的那串地址。**它属于 tab,不属于那个框。** */
  private drafts = new Map<string, string>();

  constructor(private d: TabBarDeps) {
    this.bindBar();
  }

  async load(): Promise<void> {
    try {
      const r = await this.d.api.tabs();
      this.tabs = r.tabs || [];
      this.active = r.active;
      this.render();
    } catch { /* 一次没拉到,下一条事件会再拉 */ }
  }

  private render(): void {
    const box = $("tabs");
    box.innerHTML = "";
    for (const t of this.tabs) {
      const el = document.createElement("div");
      el.className = "tab" + (t.active ? " on" : "");
      el.innerHTML = "<span></span><b>×</b>";
      // **textContent,不是 innerHTML** —— 标题是页面给的,当 HTML 塞进来就是个洞
      (el.firstChild as HTMLElement).textContent = t.title || t.url || "新标签页";
      el.title = t.url || "";
      el.onclick = (e) => {
        if ((e.target as HTMLElement).tagName === "B") {
          this.d.api.closeTab(t.id);
          return;
        }
        this.d.pick(t.id);
      };
      box.appendChild(el);
    }
    this.showUrl();
    const plus = document.createElement("div");
    plus.id = "newtab";
    plus.textContent = "＋";
    plus.onclick = () => this.d.api.newTab();
    box.appendChild(plus);
  }

  /**
   * **那串地址是 tab 的,不是这个框的。**
   *
   * 原来每次重画都无条件 `$("url").value = t.url` —— 于是**人正在打字的时候,
   * 后台随便哪个 tab 标题变了、加载完了,都会把打了一半的地址抹掉**。
   * 抹掉之后回车发出去的是别的东西(或者什么都不发),**而且一声不吭**。
   *
   * 两条规矩:
   *
   * 1. **人在这个框里,就一个字都不动它** —— 正在编辑的东西不属于渲染。
   * 2. **每个 tab 记着自己那份草稿** —— 切走再切回来,打了一半的字还在。
   *    这才是"每串地址属于它那个 tab",而不是共用一个框互相盖。
   *
   * 一个框而不是 N 个框是有意的:真浏览器也是一个地址栏,
   * 而且全屏之后屏上放不下 N 个。**问题从来不在有几个框,
   * 在于那份状态被存错了地方。**
   */
  private showUrl(): void {
    const box = $<HTMLInputElement>("url");
    if (document.activeElement === box) return;      // 人在打字,别碰
    const now = this.tabs.find((t) => t.active);
    if (!now) return;
    const draft = this.drafts.get(now.id);
    box.value = draft !== undefined ? draft : (now.url || "");
  }

  private bindBar(): void {
    const box = $<HTMLInputElement>("url");
    // 人改了就记成这个 tab 的草稿 —— 切走再回来还在
    box.addEventListener("input", () => {
      if (this.active) this.drafts.set(this.active, box.value);
    });
    box.addEventListener("blur", () => this.showUrl());
    $("url").addEventListener("keydown", (e) => {
      const ev = e as KeyboardEvent;
      if (ev.key !== "Enter" || !this.active) return;
      this.drafts.delete(this.active);                // 走了,草稿作废
      this.d.api.goto(this.active, normalizeUrl(box.value.trim()));
      box.blur();
    });
    for (const [id, verb] of [["back", "back"], ["fwd", "forward"],
                              ["reload", "reload"]] as const) {
      $(id).onclick = () => this.active && this.d.api.nav(this.active, verb);
    }
  }
}

/**
 * 地址栏里那一串到底是网址还是搜索词。
 *
 * 纯函数,所以能测 —— 而这类"看着显然"的规则恰恰是会悄悄错的:
 * 带空格的东西当网址打开会得到一个莫名其妙的 404。
 */
export function normalizeUrl(input: string): string {
  if (!input) return input;
  if (/^[a-z]+:/i.test(input)) return input;            // 已经有 scheme
  if (input.includes(".") && !input.includes(" ")) return "https://" + input;
  return "https://www.google.com/search?q=" + encodeURIComponent(input);
}
