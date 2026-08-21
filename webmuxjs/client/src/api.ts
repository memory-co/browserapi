/**
 * `/api/*` 的封装 —— 契约在 `webmuxjs/server/protocol/http.md`。
 *
 * **观看端不自己造形状。** tab 条画的是 `/api/tabs` 回的东西,
 * 和上层 SDK 拿到的是同一份 —— 内置页是**验链路的**,
 * 它用的接口必须就是别人会用的那些,否则验不出什么。
 */

/** `/api/tabs` 里的一行 —— 对应 Python 的 `models.TabInfo`。 */
export interface TabInfo {
  id: string;
  index: number;
  active: boolean;
  url: string;
  title: string;
  loading: boolean;
  security: string;
  can_go_back: boolean;
  can_go_forward: boolean;
  favicon: string | null;
  opener: string | null;
  reason: string;
  created_at: number;
  crashed: boolean;
  dialog: unknown;
}

export interface Pending {
  id: string;
  kind: "dialog" | "file" | "download" | "permission" | "auth";
  tab?: string;
  subtype?: string;
  text?: string;
  default?: string;
  mode?: string;
}

export class Api {
  /**
   * @param auth `?t=…` 或空串。**token 只在这一个地方拼**,
   *   别处都从这儿要 —— 散在各处拼的话,漏一个就是一条 401。
   */
  constructor(readonly auth: string) {}

  private url(path: string): string {
    if (!this.auth) return "/api" + path;
    return "/api" + path + (path.includes("?") ? "&" + this.auth.slice(1) : this.auth);
  }

  /** WS 地址 —— `location.protocol` 决定 ws 还是 wss。 */
  ws(path: string): string {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + path + this.auth;
  }

  /** 静态资源(重放器、xpra 客户端)也要带 token。 */
  asset(path: string): string {
    return path + this.auth;
  }

  fetch(path: string, opt?: RequestInit): Promise<Response> {
    return fetch(this.url(path), {
      headers: { "content-type": "application/json" },
      ...opt,
    });
  }

  private async json<T>(path: string, opt?: RequestInit): Promise<T> {
    return (await this.fetch(path, opt)).json() as Promise<T>;
  }

  post(path: string, body?: unknown): Promise<Response> {
    return this.fetch(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  tabs(): Promise<{ tabs: TabInfo[]; active: string | null }> {
    return this.json("/tabs");
  }

  newTab(url = "about:blank"): Promise<Response> {
    return this.post("/tabs", { url });
  }

  closeTab(id: string): Promise<Response> {
    return this.fetch("/tabs/" + id, { method: "DELETE" });
  }

  goto(id: string, url: string): Promise<Response> {
    return this.post(`/tabs/${id}/goto`, { url });
  }

  nav(id: string, verb: "back" | "forward" | "reload"): Promise<Response> {
    return this.post(`/tabs/${id}/${verb}`);
  }

  answerDialog(tab: string, accept: boolean, text: string): Promise<Response> {
    return this.post(`/tabs/${tab}/dialog`, { accept, text });
  }

  answerFiles(id: string, files: string[]): Promise<Response> {
    return this.post(`/file-chooser/${id}`, { files });
  }

  async upload(f: File): Promise<string[]> {
    const r = await this.fetch("/upload?name=" + encodeURIComponent(f.name), {
      method: "POST", body: f,
    });
    return (await r.json()).files as string[];
  }

  pending(): Promise<{ dialogs?: Pending[]; file_choosers?: Pending[] }> {
    return this.json("/pending");
  }

  viewModes(): Promise<{ available?: { name: string; label: string; blurb: string; when: string }[] }> {
    return this.json("/view/mode");
  }

  downloadUrl(id: string): string {
    return this.url("/downloads/" + id);
  }
}

/**
 * **token 进来就抹掉。** 它会进历史和 Referer ——
 * 拿到手第一件事是把它从地址栏里拿走。
 */
export function takeToken(): string {
  const t = new URLSearchParams(location.search).get("t") || "";
  if (t) history.replaceState({}, "", location.pathname);
  return t ? "?t=" + encodeURIComponent(t) : "";
}
