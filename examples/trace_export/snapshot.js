// DOM → Playwright 的 NodeSnapshot(嵌套数组)。**在我们自己的动作边界上调用。**
//
// 格式来自 packages/trace/src/snapshot.ts:
//   文本节点  → 字符串
//   元素节点  → [标签名, {属性}, ...子节点]
// 这里只发**全量**快照,不做 [[n,m]] 那种指向上一张的增量引用 ——
// 增量是带宽优化,而产物是写盘的,没有那个压力(c §13.4)。
(() => {
  const SKIP = new Set(["SCRIPT", "NOSCRIPT", "TEMPLATE"]);
  const ser = (n) => {
    if (n.nodeType === 3) return n.nodeValue;              // 文本
    if (n.nodeType !== 1) return null;
    const tag = n.nodeName;
    if (SKIP.has(tag)) return null;                        // **脚本不进快照**
    const attrs = {};
    for (const a of n.attributes || [])
      attrs[a.name] = a.name.startsWith("on") ? "" : a.value;  // 事件属性清空
    // 输入框的当前值在 DOM 属性里没有,回放要靠这两个约定键
    if (tag === "INPUT" || tag === "TEXTAREA")
      attrs["__playwright_value_"] = n.value ?? "";
    if (tag === "INPUT" && (n.type === "checkbox" || n.type === "radio"))
      attrs["__playwright_checked_"] = n.checked ? "true" : "false";
    if (n.scrollTop) attrs["__playwright_scroll_top_"] = String(n.scrollTop);
    if (n.scrollLeft) attrs["__playwright_scroll_left_"] = String(n.scrollLeft);
    const out = [tag, attrs];
    for (const c of n.childNodes) { const s = ser(c); if (s != null) out.push(s); }
    return out;
  };
  const html = ser(document.documentElement);
  // 塞一个 <base>:回放在 iframe 里,相对 URL 否则解析不到原站。
  // **只对 http(s) 塞** —— data: 不能当 base,浏览器会直接报
  // 「'data' URLs may not be used as base URLs」(实测踩到)。
  const head = html.slice(2).find((c) => Array.isArray(c) && c[0] === "HEAD");
  if (head && /^https?:$/.test(location.protocol))
    head.splice(2, 0, ["BASE", { href: location.href }]);
  return JSON.stringify({
    html,
    url: location.href,
    viewport: { width: innerWidth, height: innerHeight },
    doctype: document.doctype ? document.doctype.name : null,
  });
})()
