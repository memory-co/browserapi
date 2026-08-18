# pixels_from_xpra — 换一条像素来源,别的一律不动

## 这个场景在测什么

[docs/v2/works/11](../../docs/v2/works/11-xpra.md) 定了一条原则,
[works/12](../../docs/v2/works/12-xpra-client.md) 用实测把它落到具体形状上:

> **两个 transport 之间唯一的差别,是像素从哪来。**
> 输入、光标、tab、原生 UI、日志、token、只读 —— 一模一样。

一条原则如果没有测试钉住,下次改代码时它就只是一句话。这个场景钉的是:

1. **上行白名单是闭集。** 客户端只能往 xpra 发 6 种包,`button-action` /
   `key-action` / `pointer-position` / 剪贴板 / 文件传输**全部丢弃** ——
   这是 [03 §1](../../docs/v2/works/03-input.md) 那个安全收口在 xpra 那条路上的落点。
   而且是白名单:**新出现的包类型默认被拒**。
2. **xpra 模式下一条 `Page.startScreencast` 都不发。** 两条都开着等于同一份画面
   编码两遍。但 `Target.activateTarget` 照发 —— 切 tab 还是靠它。
3. **rencodeplus 两边对得上。** JS 编的 Python 解得开,反过来也是 ——
   这是我们自己写协议客户端(而不是借 xpra-html5)之后唯一的风险点。
4. **观看页的脚本能被解析。** 0.5.5 曾经把一行代码写进了注释里,
   整个 `<script>` 变成语法错,画面页彻底不工作,而**没有任何测试发现**。
5. **浏览器不带 bar 起。** `--kiosk` 是 `crop_top` 那一整套机制不存在的前提。

## 不在这测什么

- **真的跑一个 xpra**。要 Xvfb + xpra + PIL,而且慢。装了才跑那几条,
  没装就说没装 —— 不 mock 一个假的 xpra,那样测的是我们对它的想象。
- 画质、码率、`scroll` 省了多少 —— 那是量出来的数,写在
  [works/12 §9](../../docs/v2/works/12-xpra-client.md),不是断言。
