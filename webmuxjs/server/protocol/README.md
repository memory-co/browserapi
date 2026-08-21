# 线上那份契约

**这几篇是服务端和浏览器端之间的全部约定。** 今天由 Python 实现
([`webmuxd/`](../../../webmuxd/)),由 [`../../client/`](../../client/) 消费;
将来谁再实现一遍,照这里写的实现。

| | |
| --- | --- |
| [`frames.md`](frames.md) | 28 字节帧头、上行消息白名单 |
| [`channels.md`](channels.md) | 四条 WS 通道:各自传什么、哪条有上行 |
| [`http.md`](http.md) | `/api/*` |

## 两条贯穿的规矩

**① 上行是白名单,不是过滤。** 观看者能表达的意图只有那几种;
不在表里的消息服务端直接不认,而不是"认了再判断"
([b §1](../../../docs/v2/works/b-input.md#1-收口在哪))。

**② 一条数据只有一条路。** DOM 事件只走 `/channel/rrweb`,
不搭在 `/channel/cdp` 上;同一条事件走两条路的话客户端会重放两遍,
而增量链重放两遍出来的是一棵错的 DOM。

## 形状在哪儿

**Python 那边的对应物是 [`webmuxd/models.py`](../../../webmuxd/models.py)。**
这里写的每一个形状,在那个文件里有一个 dataclass ——
两边对不上是能测出来的([j §4.2](../../../docs/v2/works/j-layout.md#42-和-python-对拍))。
