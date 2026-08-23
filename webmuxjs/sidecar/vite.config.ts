import { resolve } from "node:path";
import { defineConfig } from "vite";

/**
 * **一个文件,IIFE,没有 import。**
 *
 * 产物要通过 `Page.addScriptToEvaluateOnNewDocument` 整段丢进别人的页面 ——
 * 那儿没有模块加载器、没有第二次请求的机会,也不该有。
 *
 * `minify: false` 是**故意的**:这段代码跑在别人的页面里,出问题时
 * 人拿到的第一手材料就是 DevTools 里的这段源码 —— 函数名、结构、
 * 那几个正则都得认得出来。压缩省下的几 KB 换不来这个。
 * (注释留不住,esbuild 一律去掉;为什么这么写在 `src/` 里。)
 *
 * **入口不导出任何东西**,所以产物是一段干干净净的 IIFE:
 * 它在别人的页面里只留一个 `window.__wm_side` 作幂等标记,
 * 不多挂一个全局。足迹小一点是本分,不是洁癖。
 */
export default defineConfig({
  build: {
    lib: {
      entry: resolve(__dirname, "src/index.ts"),
      formats: ["iife"],
      name: "__wm_sidecar",
      fileName: () => "sidecar.js",
    },
    minify: false,
    target: "es2020",
    emptyOutDir: true,
  },
  test: { environment: "jsdom", include: ["test/**/*.test.ts"] },
});
