/**
 * 页面往回说话的**唯一一个口子**。
 *
 * `Runtime.addBinding` 在页面里装了一个函数,页面调它,sessiond 那边收到
 * 一条 `Runtime.bindingCalled`。**全项目就这一个 binding**
 * ([b §6](../../../docs/v2/works/b-input.md))—— 探针改变了页面环境这件事
 * 本来就要如实承认,那就更没理由多开一个。
 *
 * 名字必须和 `webmuxd/probe.py` 里的 `BINDING` 一个字不差。
 * 两处各写一遍是行不通的:改了一边,页面照样调、binding 照样在,
 * **服务端一条都收不到,而且不报错**。所以那边有一条测试盯着这两个字符串。
 */
export const BINDING = "__webmuxd";

/** 这一条是什么。**服务端按它分发**,不猜。 */
export type Kind = "pointerdown" | "keydown" | "cursor" | "foreground";

type Binding = (payload: string) => void;

/**
 * 往回报一条。
 *
 * **永远不抛。** 调用点全都在事件回调里(`pointermove`、`visibilitychange`),
 * 抛出去就是往页面自己的控制台里扔我们的错 —— 页面没做错任何事。
 * binding 不在也是正常的:导航之后它会短暂消失,下一次注入会补上。
 */
export function send(kind: Kind, extra: Record<string, unknown> = {}): void {
  try {
    const fn = (window as unknown as Record<string, Binding | undefined>)[BINDING];
    if (typeof fn !== "function") return;
    fn(JSON.stringify({ kind, ...extra }));
  } catch {
    /* 页面把 JSON 换掉了、binding 半死不活 —— 都不是我们能修的 */
  }
}

export type Send = typeof send;
