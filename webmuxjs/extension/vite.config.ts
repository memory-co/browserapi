import { copyFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";

/** `manifest.json` 原样拷过去 —— 它不是代码,不该被打包器碰。 */
function manifest(): Plugin {
  return {
    name: "webmuxd-manifest",
    closeBundle() {
      copyFileSync(resolve(__dirname, "src/manifest.json"),
                   resolve(__dirname, "dist/manifest.json"));
    },
  };
}

/**
 * **产物是一个目录,不是一个文件。** `--load-extension=` 只收目录 ——
 * 这是它和 [`../sidecar/`](../sidecar/) 在打包上唯一的实质差别。
 *
 * `minify: false` 同 sidecar:这段代码跑在一个有特权的上下文里,
 * 出问题时人拿到的第一手材料就是 DevTools 里的这段源码。
 */
export default defineConfig({
  plugins: [manifest()],
  build: {
    lib: {
      entry: resolve(__dirname, "src/sw.ts"),
      formats: ["iife"],
      name: "__wm_ext",
      fileName: () => "sw.js",
    },
    minify: false,
    target: "es2020",
    emptyOutDir: true,
  },
  test: { environment: "node", include: ["test/**/*.test.ts"] },
});
