/**
 * 内置页的路由 —— **地址说了算**。
 *
 *     /            → 那张 session 列表
 *     /s/demo/     → demo 的画面
 *
 * 服务端两条路由回的是**同一个文件**,认路在这儿
 * ([k §4](../../../../docs/v2/works/k-one-server.md#4-路由sid-前缀))。
 *
 * 观看那一整套(通道、输入、tab 条)在 `session-view.ts` 里,
 * 它**导出一个函数** —— 列表页这条路上根本不调,于是一条 WebSocket 都不连。
 *
 * > 试过用 `import()` 动态加载,不行:产物要单文件(token 那条,见
 * > `vite.config.ts`),而 `inlineDynamicImports` 会把动态 import 变成静态,
 * > **那一整套就无条件跑起来了** —— 列表页上直接报"模板里没有 #screen"。
 * > 条件执行要用函数表达,不要用模块副作用。
 */

import { currentSession, takeToken } from "../api.ts";
import { startSessionView } from "./session-view.ts";
import { renderSessions } from "./sessions.ts";

const auth = takeToken();
const sid = currentSession();

if (sid) startSessionView(auth, "/s/" + encodeURIComponent(sid));
else renderSessions(auth);
