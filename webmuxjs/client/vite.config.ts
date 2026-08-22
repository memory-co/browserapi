import { readFileSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";

// **开发时把 /api 和 /channel 代理到本机 sessiond。**
// `npm run dev` 之后改一行 .ts 立刻生效,不用先构建再拷进包里。
const SESSIOND = process.env.WEBMUXD_DEV_TARGET || "http://127.0.0.1:7900";

/**
 * **把 JS 内联进 index.html,产物只有一个文件。**
 *
 * 不是为了省一个请求,是为了 token:观看链接是 `/?t=<token>`,
 * 而 `<script src="./index.js">` 这个二次请求**不会带上那个 query** ——
 * 于是脚本 403,页面白屏,而且第一眼看不出为什么。
 *
 * 内联之后整页就是一个响应,和加 token 之前的行为一模一样。
 * 内置页本来也不大(二十几 KB),分块买不到任何东西。
 */
function singleFile(): Plugin {
  return {
    name: "webmuxd-single-file",
    enforce: "post",
    generateBundle(_opts, bundle) {
      const js = Object.values(bundle).find(
        (c) => c.type === "chunk" && c.isEntry,
      );
      const html = Object.values(bundle).find(
        (c) => c.type === "asset" && c.fileName.endsWith(".html"),
      );
      if (!js || js.type !== "chunk" || !html || html.type !== "asset") return;
      html.source = String(html.source).replace(
        /<script[^>]*src="[^"]*"[^>]*><\/script>/,
        `<script type="module">\n${js.code}\n</script>`,
      );
      delete bundle[js.fileName];
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [singleFile()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "[name].js", assetFileNames: "[name][extname]",
      },
    },
  },
  server: {
    proxy: {
      "/api": { target: SESSIOND, ws: true, changeOrigin: true },
      "/channel": { target: SESSIOND, ws: true, changeOrigin: true },
    },
  },
  test: { environment: "node", include: ["test/**/*.test.ts"] },
});
