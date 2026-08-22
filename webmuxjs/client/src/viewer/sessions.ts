/**
 * `/` 上那张 session 列表 —— **`tmux ls` 的样子,不是仪表盘**。
 *
 * 一行一个:名字、几个 tab、画面走哪条。没有 CPU 曲线,没有设置面板
 * ([k §3](../../../../docs/v2/works/k-one-server.md#3-那个口上看到什么))。
 *
 * 空的时候说一句怎么建 —— **"暂无"本身不是信息,"接下来做什么"才是。**
 */

import { ServerApi, type SessionRow } from "../api.ts";

const CSS = `
#list{max-width:720px;margin:64px auto;padding:0 20px;
  font:14px/1.6 system-ui,-apple-system,"PingFang SC",sans-serif}
#list h1{font-size:15px;font-weight:600;margin:0 0 4px;letter-spacing:.02em}
#list .sub{color:#8a8f98;margin:0 0 24px}
#list a.row{display:flex;gap:12px;align-items:baseline;padding:11px 14px;
  margin:0 -14px;border-radius:6px;color:inherit;text-decoration:none}
#list a.row:hover{background:#ffffff10}
#list .id{font-weight:600;min-width:9em}
#list .meta{color:#8a8f98;font-size:13px}
#list .tag{border:1px solid #ffffff28;border-radius:3px;padding:0 5px;
  font-size:11px;color:#b9bec6}
#list .empty{border:1px dashed #ffffff28;border-radius:8px;padding:22px;
  color:#8a8f98}
#list code{background:#ffffff14;border-radius:4px;padding:2px 6px;
  font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:#e6e9ef}
`;

export function renderSessions(auth: string): void {
  document.body.innerHTML = '<div id="list"></div>';
  const style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);
  const box = document.getElementById("list")!;

  const paint = (rows: SessionRow[]) => {
    box.innerHTML = "";
    const h = document.createElement("h1");
    h.textContent = "webmuxd";
    const sub = document.createElement("p");
    sub.className = "sub";
    sub.textContent = rows.length
      ? `${rows.length} 个 session`
      : "这个 server 上还没有 session";
    box.append(h, sub);

    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.innerHTML = "起一个:<code>webmuxd new --id demo</code>";
      box.append(empty);
      return;
    }
    for (const r of rows) {
      const a = document.createElement("a");
      a.className = "row";
      a.href = r.url;
      const id = document.createElement("span");
      id.className = "id";
      id.textContent = r.id;                 // **textContent** —— 名字是人给的
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = r.view_label;
      const meta = document.createElement("span");
      meta.className = "meta";
      meta.textContent = `${r.tabs} 个 tab · ${r.runtime} · ${mins(r.uptime_s)}`;
      a.append(id, tag, meta);
      box.append(a);
    }
  };

  const api = new ServerApi(auth);
  const tick = () => api.sessions().then((d) => paint(d.sessions)).catch(() => {
    box.innerHTML = '<p class="sub">连不上 server</p>';
  });
  tick();
  // **列表是轮询的,不开 WS。** 一个几行的清单不值得一条长连接;
  // 而画面那条连接是 `/s/<id>/` 里才有的事。
  setInterval(tick, 2000);
}

function mins(s: number): string {
  if (s < 60) return `${s} 秒`;
  if (s < 3600) return `${Math.floor(s / 60)} 分钟`;
  return `${Math.floor(s / 3600)} 小时`;
}
