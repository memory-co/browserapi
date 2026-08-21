/** `document.getElementById` 的短名字,加上一句"找不到就当场炸"。 */
export function $<T extends HTMLElement = HTMLElement>(id: string): T {
  const el = document.getElementById(id);
  // **找不到就炸,不返回 null。** 内置页的 DOM 是我们自己写死的,
  // 少一个 id 是模板改坏了 —— 让它当场响,别变成后面一串 `?.`。
  if (!el) throw new Error(`模板里没有 #${id}`);
  return el as T;
}

export function toast(html: string, ms = 8000): void {
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = html;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), ms);
}
