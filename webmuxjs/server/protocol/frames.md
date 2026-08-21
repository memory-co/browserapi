# 帧头与上行消息

## 1. 28 字节定长头

**头 + 图片裸字节,不是 JSON。** CDP 给的是 base64,原样塞进 JSON 转发
要多花 33% 体积和两次编解码。

```
偏移   长度   内容
0      4     castSessionId   每次 startScreencast 递增,用来丢弃切 tab 前的残帧
4      4     frameId         单调递增
8      16    targetId        32 个 hex 字符切成 4 个 uint32 LE
24     4     保留(全 0)
```

**全部 little-endian。** 这一条曾经靠人肉发现 ——
所以它现在有对拍 fixture(`client/fixtures/frame-header.json`)。

`targetId` 短了补 `0`、长了截断:**头是定长的**,
绝不能因为一个奇怪的 targetId 就让整条流错位。

Python 侧:[`webmuxd/frames.py`](../../../webmuxd/frames.py)、
[`models.FrameHeader`](../../../webmuxd/models.py)。

## 2. 客户端怎么用这个头

两条丢帧规则,缺一条都会看到闪烁:

- `castSessionId` **比当前小**的丢 —— 那是上一轮 startScreencast 的残帧
- `targetId` **和当前 tab 对不上**的丢 —— 切 tab 的瞬间管道里还有旧的

## 3. 上行消息(白名单)

```
ack      收到一帧 —— {type, frameId}
mouse    {type, event: move|down|up, x, y, button?, buttons?, clicks?, modifiers}
wheel    {type, x, y, dx, dy, modifiers}
key      {type, event: down|up, key, code, modifiers}
text     {type, text}          —— IME 组好的最终文本、粘贴
resize   {type, w, h}
tab      {type, id}
mode     {type, mode}          —— 换一种画面,只换画面来源
```

`modifiers` 是位:`Alt=1 Ctrl=2 Meta=4 Shift=8`。

坐标 `x` / `y` 是**画面坐标**(不是 CSS 像素、不是物理像素)——
客户端按 `castW / 元素宽度` 换算好再发。

**这张表就是全部。** 没有"执行 JS"、没有"导航",
那些走 HTTP 且要凭证([`http.md`](http.md))。

## 4. 下行 JSON 消息

```
hello        {type, writable, transport, w, h}   —— 连上来第一条
cast         {type, tab, w, h, format, quality}  —— 开始/重开一轮
quality      {type, quality, every_nth}          —— 降质/抽帧
mode         {type, mode, label, why, available} —— 换成了哪种
mode_error   {type, message, hint}               —— **切不动要说清楚,不静默留在原来那种**
cursor       {type, cursor}                      —— 已过白名单的 CSS cursor 值
```
