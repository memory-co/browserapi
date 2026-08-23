/**
 * **注进页面里的那一段** —— 一个文件、一次注入、一个 binding。
 *
 * 原来这些是四段 Python 字符串字面量,散在 `probe.py` / `cursor.py` 里,
 * 各自 `addBinding` + `addScriptToEvaluateOnNewDocument` + `evaluate` 一遍。
 * 那套仪式咬过两次,而且两次的表现都是"什么都没发生,也没有错"
 * (`probe.enable` 的 docstring 记着)。四份一样的仪式就是四次犯同一个错的机会。
 *
 * 搬到这儿之后多了三样原来没有的:**类型检查、单元测试、一处改一处生效**。
 * 这段代码跑在别人的页面里,是全项目最该被这三样管住的地方 ——
 * 密码明文那次就是从这儿漏出去的(见 `label.ts`)。
 *
 * ## 一条硬规矩
 *
 * **一个探针塌了,不许带走其它几个。** 它们凑在同一个 bundle 里之后,
 * 一个没接住的异常会让后面的全部装不上 —— 而分成四段的时候不会。
 * 所以下面每一个都单独 try 住:合并是为了少犯错,不是为了多一种坏法。
 */

import { install as openShim } from "./open-shim.ts";
import { install as inputWatch } from "./input-watch.ts";
import { install as cursor } from "./cursor.ts";
import { install as foreground } from "./foreground.ts";
import { send, type Send } from "./wire.ts";

declare global {
  interface Window {
    __wm_side?: true;
  }
}

/** 装哪几个。**顺序无关** —— 它们之间没有依赖,这一点是有意保持的。 */
const PROBES: Array<[string, (send: Send) => void]> = [
  ["open", () => openShim()],
  ["input", inputWatch],
  ["cursor", cursor],
  ["foreground", foreground],
];

function install(): void {
  // 幂等。`addScriptToEvaluateOnNewDocument` 装的那份和对当前文档
  // `evaluate` 的那份会在同一个文档里都跑到。
  if (window.__wm_side) return;
  window.__wm_side = true;

  for (const [name, fn] of PROBES) {
    try {
      fn(send);
    } catch (e) {
      // **报出来,别咽掉。** 一个探针没装上意味着某个功能整个不工作
      // (光标永远是箭头 / 人的操作不进流水),而那种坏静悄悄的。
      try {
        console.warn("[webmuxd] 探针没装上:" + name, e);
      } catch {
        /* 页面把 console 换掉了 */
      }
    }
  }
}

install();
