# tab_identity — tab 表就是浏览器的 target 表

## 这个场景在测什么

webmuxd 承诺"tab 表不是黑盒,就是浏览器自己那张表"。这个场景锁的是这句话的拐点:

1. **`t_N` 永不复用。** id 复用会让"这条日志说的是哪个 tab"变成猜。
2. **`reason` 分得清是谁开的** —— `api` / `page` / `user` / `restored`,
   判据只有一个:`targetInfo.openerId` 在不在。
3. **关掉和被挤掉是两回事。** `closed` 是你要的,`evicted` 是上限逼的 ——
   报错混在一起会让人以为自己关过。
4. **超上限先建后挤**,而且刚建出来的那个不能被自己挤掉。
5. 只收 `page` 类型的 target —— 不过滤的话 service worker 会跑进 tab 条。

## 不在这测什么

- **`open()` 怎么落到 Chromium、事件怎么推上来** —— 那是 CDP 的事实,
  在 [`f-tabs.md §openerId`](../../docs/v2/works/f-tabs.md) 里写着,
  端到端由 [`v2_cli_new_tab/`](../v2_cli_new_tab/) 守着。
- **lib 那边 `tab.url` 读的是内存还是发请求** —— 在 [`session_identity/`](../session_identity/)。
