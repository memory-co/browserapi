/**
 * **探针不许读表单控件的 `value`。**
 *
 * 这条规矩是拿一次泄露换来的:原来那行是 `innerText || value`,
 * 而密码框的 `value` 就是明文密码 —— 它进了 `log.jsonl`,
 * `webmuxd log` 打得出来、`webmuxd bundle` 打包带得走。
 *
 * 这些用例存在的全部意义是:**那一行再也改不回去而不被发现。**
 * 端到端那几条测不到它 —— 它们不会往密码框里打真密码。
 */

import { describe, expect, it } from "vitest";
import { label } from "../src/label.ts";

function el(html: string): Element {
  const box = document.createElement("div");
  box.innerHTML = html;
  return box.firstElementChild!;
}

describe("控件的身份", () => {
  it("密码框:什么都没有的时候,宁可说不出来,也不拿 value 顶", () => {
    const input = el('<input type="password">') as HTMLInputElement;
    input.value = "hunter2";
    expect(label(input)).toBe("");
  });

  it("四样标签都没有的普通输入框,也是空的", () => {
    const input = el('<input type="text">') as HTMLInputElement;
    input.value = "我刚打的字";
    expect(label(input)).toBe("");
  });

  it("select 和 textarea 一样不许拿内容顶", () => {
    const ta = el("<textarea>写了一半的东西</textarea>");
    expect(label(ta)).toBe("");
    const sel = el("<select><option>选项一</option></select>");
    expect(label(sel)).toBe("");
  });

  it("有 aria-label 就用它,而且它排在最前", () => {
    const input = el('<input type="password" aria-label="密码" placeholder="请输入">');
    (input as HTMLInputElement).value = "hunter2";
    expect(label(input)).toBe("密码");
  });

  it("没有 aria-label 就退到 placeholder", () => {
    expect(label(el('<input type="text" placeholder="搜点什么">'))).toBe("搜点什么");
  });

  it("再没有就退到 name / id —— 它们是页面作者写的,不是人打的", () => {
    expect(label(el('<input type="text" name="q">'))).toBe("q");
    expect(label(el('<input type="text" id="kw">'))).toBe("kw");
  });

  it("不是表单控件的,才轮到 innerText", () => {
    const b = el("<button>搜一下</button>") as HTMLElement;
    // **jsdom 没有 `innerText`**(它只实现了 `textContent`)——
    // 这儿补上,免得这条用例其实在验 jsdom 的缺口而不是我们的判断。
    Object.defineProperty(b, "innerText", { value: b.textContent });
    expect(label(b)).toBe("搜一下");
  });

  it("<label for> 指过来的,排在 placeholder 前面", () => {
    const box = document.createElement("div");
    box.innerHTML = '<label for="pw">口令</label><input id="pw" type="password" placeholder="请输入">';
    document.body.appendChild(box);
    const input = box.querySelector("input")!;
    const lab = box.querySelector("label") as HTMLElement;
    Object.defineProperty(lab, "innerText", { value: lab.textContent });
    input.value = "hunter2";
    expect(label(input)).toBe("口令");
    box.remove();
  });

  it("null 不炸", () => {
    expect(label(null)).toBe("");
  });
});
