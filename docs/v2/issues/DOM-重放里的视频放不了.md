# DOM 重放里的 `<video>` 放不了

**状态**:**已定位,未修**(2026-08-23,写 `v2_browser_dom` 时撞上)。
**影响**:DOM 模式下,页面里的视频在重放里是一块空的播放器,
观看端的 console 上留一条 `Failed to load because no supported source was found`。
图片、字体、CSS 都正常 —— **只有需要边下边播的东西不行**。

## 现象

百度首页上有一个 `<video>`(那个对话入口的动效)。重放里:

```js
{tag: 'VIDEO',
 src: 'api/res?u=https%3A%2F%2Fpsstatic.cdn.bcebos.com%2F…',
 错误码: 4}                       // MEDIA_ELEMENT_ERROR:格式不支持
```

地址是**转发过的**(`/s/{sid}/api/res`,那条路走通了,见 CHANGELOG 0.13.x),
东西也取回来了 —— 但浏览器还是放不了。

## 为什么

`h_res`([serve.py](../../../webmuxd/serve.py))是**整个 body 一次给完**:

```python
return web.Response(body=blob, content_type=…)
```

而媒体元素要的是 **range 请求**:它先要一小段探格式,再按需取。
我们既不认 `Range` 头,也不回 `206` / `Accept-Ranges` ——
于是浏览器拿到一坨没法按需读的字节,判成"没有可用的源"。

顺带还有一条:整段视频要先**在服务端内存里存一份**才能转发,
而视频动辄几 MB —— 那条路本来就不该是为视频设计的。

## 修的话要做什么

- `h_res` 认 `Range`,回 `206` + `Content-Range` + `Accept-Ranges: bytes`。
- 视频**不进内存缓存**,改成边取边转(或者干脆 302 回原站)。

## 今天为什么不修

DOM 这条腿的定位是**文字为主的页面、网络差的时候用**
([c §9.1](../works/c-view.md))—— 要看视频的人本来就该切 JPG 或 VNC。
先把它写下来,不让它以"偶尔有条 console 错"的样子飘着。

`v2_browser_dom` 里对这一条是**指名放行**的:除了它,别的错一条都不许有。
