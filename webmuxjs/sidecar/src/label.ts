/**
 * **一个控件的身份是它的标签,不是它的内容。**
 *
 * 这个文件单独存在,只为了守住一条规矩:
 *
 * > **探针不许读表单控件的 `value`。**
 *
 * 这条规矩是拿事故换来的。原来那行是 `innerText || value` ——
 * 而 `value` 在密码框上就是明文密码,它会被写进 `log.jsonl`,
 * `webmuxd log` 打得出来、`webmuxd bundle` 打包带得走。
 * `log.py` 里那条掩码只管 API 那条路,**人从画面进来的这条绕过去了**。
 * 实测过,确实漏。
 *
 * 所以判据只取这四样:`aria-label` → `<label>` → `placeholder` → `name`/`id`。
 * 四样都没有而它是个表单控件,**就返回空字符串** —— 说不出来就不说,
 * 不拿内容顶上。
 */

const FORM = /^(input|textarea|select)$/i;

export function label(el: Element | null): string {
  if (!el || !el.getAttribute) return "";

  const aria = el.getAttribute("aria-label");
  if (aria) return aria;

  const labels = (el as HTMLInputElement).labels;
  const first = labels && labels.length ? labels[0] : undefined;
  if (first && first.innerText) return first.innerText;

  const ph = el.getAttribute("placeholder");
  if (ph) return ph;

  const nm = el.getAttribute("name") || el.id;
  if (nm) return nm;

  // **到这儿就停。** 下面那句 `innerText` 对表单控件是不许走的 ——
  // 见文件头。
  if (FORM.test(el.tagName || "")) return "";
  return (el as HTMLElement).innerText || "";
}
