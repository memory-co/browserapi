/**
 * `/channel/rrweb` —— **只下行。**
 *
 * 注意这个文件里**没有发送函数**。不是"发之前判断一下",
 * 是结构上就没有那条路 —— 服务端那个 handler 里同样没有接收端
 * (`server/protocol/channels.md`)。
 *
 * DOM 事件不搭在 `/channel/cdp` 上:一条数据只该有一条路,
 * 两条都发的话客户端会重放两遍,而**增量链重放两遍出来的是一棵错的 DOM**。
 *
 * 断了只是画面停住,**输入照常送达** —— 所以这儿只重连,
 * 不把整个会话判成不可用。
 */

export class RrwebChannel {
  private ws: WebSocket | null = null;
  private wanted = false;

  constructor(private url: string, private onEvent: (e: unknown) => void) {}

  connect(): void {
    this.wanted = true;
    if (this.ws && this.ws.readyState <= 1) return;
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data as string);
      if (m.type === "dom") this.onEvent(JSON.parse(m.e));
    };
    ws.onclose = () => {
      if (this.wanted) setTimeout(() => this.connect(), 1000);
    };
  }

  /** 切走了就别占着这条连接。 */
  close(): void {
    this.wanted = false;
    this.ws?.close();
    this.ws = null;
  }
}
