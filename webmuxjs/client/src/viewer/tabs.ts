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
      if (t.active) $<HTMLInputElement>("url").value = t.url || "";
    }
    const plus = document.createElement("div");
    plus.id = "newtab";
    plus.textContent = "＋";
    plus.onclick = () => this.d.api.newTab();
    box.appendChild(plus);
  }

  private bindBar(): void {
    $("url").addEventListener("keydown", (e) => {
      const ev = e as KeyboardEvent;
      if (ev.key !== "Enter" || !this.active) return;
      this.d.api.goto(this.active, normalizeUrl($<HTMLInputElement>("url").value.trim()));
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
