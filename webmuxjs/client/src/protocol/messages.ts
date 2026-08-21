/**
 * 上行消息 —— **白名单,以及构造它们的那几个函数**。
 *
 * 契约在 `webmuxjs/server/protocol/frames.md` §3。
 * 收口的意思是:**观看者能表达的意图只有这张表里这些**
 * ([b §1](../../../../docs/v2/works/b-input.md#1-收口在哪))。
 * 没有"执行 JS",没有"导航" —— 那些走 HTTP 且要凭证。
 *
 * 纯逻辑,不碰 DOM。DOM 事件怎么变成这些,在 `src/input/`。
 */

export const UPSTREAM = [
  "ack", "mouse", "wheel", "key", "text", "resize", "tab", "mode",
] as const;

export type UpstreamType = (typeof UPSTREAM)[number];

/** 位:Alt=1 Ctrl=2 Meta=4 Shift=8。 */
export const MOD = { alt: 1, ctrl: 2, meta: 4, shift: 8 } as const;

export interface Ack { type: "ack"; frameId: number }
export interface Mouse {
  type: "mouse"; event: "move" | "down" | "up";
  x: number; y: number;
  button?: number; buttons?: number; clicks?: number; modifiers: number;
}
export interface Wheel {
  type: "wheel"; x: number; y: number; dx: number; dy: number; modifiers: number;
}
export interface Key {
  type: "key"; event: "down" | "up"; key: string; code: string; modifiers: number;
}
export interface Text { type: "text"; text: string }
export interface Resize { type: "resize"; w: number; h: number }
export interface TabPick { type: "tab"; id: string }
export interface ModePick { type: "mode"; mode: string }

export type Upstream =
  | Ack | Mouse | Wheel | Key | Text | Resize | TabPick | ModePick;

export const ack = (frameId: number): Ack => ({ type: "ack", frameId });
export const resize = (w: number, h: number): Resize => ({ type: "resize", w, h });
export const pickTab = (id: string): TabPick => ({ type: "tab", id });
export const pickMode = (mode: string): ModePick => ({ type: "mode", mode });
export const text = (t: string): Text => ({ type: "text", text: t });

/**
 * **发之前最后一道。** 服务端也有同一张表 —— 两边都守,
 * 是因为这张表就是安全模型本身,只有一侧守着的话,
 * 另一侧的一次疏忽就是一个洞。
 */
export function allowed(m: { type?: string }): boolean {
  return UPSTREAM.includes(m.type as UpstreamType);
}

// ---------------------------------------------------------------- 下行

export interface Hello {
  type: "hello"; writable: boolean; transport: string; w?: number; h?: number;
}
export interface Cast {
  type: "cast"; tab?: string; w: number; h: number; format?: string; quality?: number;
}
export interface QualityMsg { type: "quality"; quality: number; every_nth: number }
export interface ModeMsg {
  type: "mode"; mode: string; label: string; why?: string;
  available?: { name: string; label: string; blurb: string; when: string }[];
}
export interface ModeError { type: "mode_error"; message: string; hint?: string }
export interface Cursor { type: "cursor"; cursor: string }

export type Downstream =
  | Hello | Cast | QualityMsg | ModeMsg | ModeError | Cursor;
