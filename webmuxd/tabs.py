"""tab 表 —— sessiond 那份唯一真相。

docs/v1/works/06-tab-sync.md 和 docs/v1/api/tabs.md 是这份代码的规格。

三条贯穿的规矩,写在最前面因为它们解释了下面所有看起来奇怪的地方:

1. **`t_N` 是我们自己分配的,关掉之后不复用。** CDP 的 targetId 是 32 位 hex、
   Chromium 一重启就全变;而日志和历史观测里的 `t_7` 必须永远指同一个东西。
2. **`active` 不是观测出来的,是我们记的。** CDP 根本没有"tab 被激活了"这种事件,
   所以别去猜 —— 我们改自己的字段,再用 `Target.activateTarget` 把 Chromium 拽过来对齐。
3. **同时开着的 tab 有上限,超了挤掉最不活跃的。** 每个活着的 tab 是一个渲染进程,
   而失控的通常不是人,是页面 `window.open` 一串或者循环里忘了关。
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
import time
from contextlib import suppress
from typing import Any, Callable

from webmuxd.cdp import CDP, CDPError
from webmuxd.exceptions import BadRequest, TabGone
from webmuxd.models import TabInfo

log = logging.getLogger("webmuxd.tabs")

#: 同时开着的 tab 上限,超了挤掉最不活跃的(api/tabs.md §3)。
TAB_MAX = int(os.environ.get("WEBMUXD_TAB_MAX", "10"))

#: 特权页面禁止导航 —— 不是做不到,是不该做(api/tabs.md §3)。
BLOCKED_SCHEMES = ("chrome://", "chrome-untrusted://", "devtools://",
                   "chrome-extension://", "view-source:")


def is_blocked(url: str) -> bool:
    u = (url or "").strip().lower()
    return any(u.startswith(s) for s in BLOCKED_SCHEMES)


class TabTable:
    """活着的 tab,加上"当前是哪个"。

    事件通过 `emit` 出去(`(type, payload)`),seq 由调用方统一分配 ——
    日志和事件流共用一个计数器,这样两边对得齐(works/06 §5)。
    """

    def __init__(
        self,
        cdp: CDP,
        *,
        emit: Callable[[str, dict], Any] | None = None,
        tab_max: int = TAB_MAX,
    ) -> None:
        self._cdp = cdp
        self._emit = emit or (lambda *_: None)
        self._tab_max = tab_max

        self._by_id: dict[str, TabInfo] = {}
        self._by_target: dict[str, str] = {}
        self._order: list[str] = []
        self._active: str | None = None
        self._ids = itertools.count(1)
        #: 退役的号不复用,并且记着**为什么**退役 —— 调用方要分得清
        #: "你关的"和"被挤掉的"(api/tabs.md §3)。
        self._retired: dict[str, dict[str, Any]] = {}
        #: 我们自己发起的 createTarget,用来把 reason 判成 api。
        self._expect_api: set[str] = set()
        self._busy: set[str] = set()
        #: 正在被挤掉的 target。**`await closeTarget` 期间事件会先到** ——
        #: 见 `_evict_if_needed`。
        self._evicting: set[str] = set()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ 读

    @property
    def active(self) -> str | None:
        return self._active

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, tab_id: object) -> bool:
        return tab_id in self._by_id

    def get(self, tab_id: str) -> TabInfo:
        tab = self._by_id.get(tab_id)
        if tab is None:
            why = self._retired.get(tab_id, {"reason": "closed"})
            raise TabGone(f"{tab_id} 不在了", code="tab_gone", details=dict(why))
        return tab

    def index_of(self, tab_id: str) -> int:
        return self._order.index(tab_id)

    def list(self) -> list[TabInfo]:
        """当前这些 tab,**顺序和"哪个是当前"已经填进对象里**。

        给的是 `TabInfo` 不是 dict —— 要 JSON 的自己 `to_json()`
        ([j §3.1](../docs/v2/works/j-layout.md#31-modelspy所有跨边界的数据在这儿定义一次))。
        """
        out = []
        for n, i in enumerate(self._order):
            t = self._by_id[i]
            t.index, t.active = n, i == self._active
            out.append(t)
        return out

    def list_json(self) -> dict[str, Any]:
        return {"tabs": [t.to_json() for t in self.list()], "active": self._active}

    # ------------------------------------------------------------- 接 CDP

    async def start(self) -> None:
        """开好订阅,然后把已经存在的 target 收进来。

        `setDiscoverTargets` 会把**已存在的** target 各补一条 `targetCreated`
        (实测,works/06 §7),所以不用再单独走一遍 `getTargets` ——
        但重连之后仍然要对账,那是调用方的事。
        """
        self._cdp.on("Target.targetCreated", self._on_created)
        self._cdp.on("Target.targetDestroyed", self._on_destroyed)
        self._cdp.on("Target.targetInfoChanged", self._on_info)
        await self._cdp.send("Target.setDiscoverTargets", {"discover": True})
        # **新 target 先暂停,等我们注入完再放行。**
        # `Target.createTarget({url})` 一建出来页面就开始加载,而注入是 attach
        # 之后才做的 —— 中间那一小段就是竞态:同样的代码,一次探到记录器在,
        # 下一次是 `undefined`,**而且不报错**。
        #
        # 放行在 `Session.executor_for()` 末尾(注入全做完那一刻)。
        # 谁要是不放行,那个 tab 就永远停在那儿 —— 所以那边还挂了个看门狗。
        await self._cdp.send(
            "Target.setAutoAttach",
            {"autoAttach": True, "flatten": True, "waitForDebuggerOnStart": True},
        )

    def _on_created(self, params: dict, _sid: str | None) -> None:
        info = params.get("targetInfo", {})
        # 只收 page —— targetCreated 推的是所有 target,不过滤的话
        # service worker 会跑进 tab 条(works/06 §2)。
        if info.get("type") != "page" or info.get("targetId") in self._by_target:
            return
        asyncio.create_task(self._adopt(info))

    def _on_destroyed(self, params: dict, _sid: str | None) -> None:
        target = params.get("targetId", "")
        tab_id = self._by_target.get(target)
        if tab_id:
            # **是我们挤的,还是它自己没了 —— 这两件事对使用者是不同的**
            # (api/tabs.md §3)。`_evicting` 是唯一分得清的地方:
            # 这条事件可能比 `closeTarget` 的响应先到,那时候还没人说过"evicted"。
            reason = "evicted" if target in self._evicting else "closed"
            self._forget(tab_id, reason=reason)

    def _on_info(self, params: dict, _sid: str | None) -> None:
        info = params.get("targetInfo", {})
        tab_id = self._by_target.get(info.get("targetId", ""))
        if not tab_id:
            return
        self.update(tab_id, url=info.get("url", ""), title=info.get("title", ""))

    #: 没有 openerId 的 target,要么是我们建的、要么是人按 Ctrl+T 开的。
    #: `targetCreated` 事件比 `createTarget` 的响应先到(同一条 ws,事件在前),
    #: 所以给 open() 一个很短的窗口去认领。人开的只是晚这么点被宣告,无所谓。
    _CLAIM_GRACE = 0.05

    async def _adopt(self, info: dict) -> None:
        if not info.get("openerId"):
            deadline = time.monotonic() + self._CLAIM_GRACE
            while time.monotonic() < deadline and info["targetId"] not in self._expect_api:
                await asyncio.sleep(0.005)

        async with self._lock:
            target_id = info["targetId"]
            if target_id in self._by_target:
                return
            tab_id = f"t_{next(self._ids)}"

            opener_target = info.get("openerId")
            opener = self._by_target.get(opener_target) if opener_target else None
            reason = self._reason_for(target_id, opener_target)

            tab = TabInfo(id=tab_id, target_id=target_id, url=info.get("url", ""),
                      title=info.get("title", ""), opener=opener, reason=reason)
            self._by_id[tab_id] = tab
            self._by_target[target_id] = tab_id
            self._order.append(tab_id)
            self._expect_api.discard(target_id)

            if self._active is None:
                self._active = tab_id
            self._emit("tab.created", {"tab": tab.to_json(
                index=self.index_of(tab_id), active=tab_id == self._active), "reason": reason})

        # protect:刚建出来的那个不能被自己挤掉(api/tabs.md §3「先建后挤」)。
        # 光靠 LRU 顺序保护不住 —— 上限很小时,排除掉激活的之后,
        # 唯一的候选恰好就是它自己。
        await self._evict_if_needed(protect=tab_id)

    def _reason_for(self, target_id: str, opener_target: str | None) -> str:
        """**判据就是 openerId 在不在。**

        实测(Chromium 124):`window.open`、`window.open(...,'noopener')`、
        `<a target=_blank>`、`<a target=_blank rel=noopener>` **四种全都带 openerId**
        —— `noopener` 切断的是页面侧的 `window.opener`,而 openerId 是浏览器层的
        血缘记录,两回事。所以不需要拿 url 兜底,也不需要一个 `unknown`。
        """
        if target_id in self._expect_api:
            return "api"
        return "page" if opener_target else "user"

    # ------------------------------------------------------------ 增删改

    async def open(self, url: str = "about:blank", *, activate: bool = True) -> TabInfo:
        if is_blocked(url):
            raise BadRequest(f"{url} 是特权页面,禁止导航", code="blocked_url",
                             details={"url": url})
        # createTarget 本来就收 url,所以建 + 导航是一次调用(works/06 §1)
        r = await self._cdp.send("Target.createTarget", {"url": url})
        target_id = r["targetId"]
        self._expect_api.add(target_id)   # 认领 —— _adopt 那边正等着看

        for _ in range(400):           # targetCreated 是推的,等它到
            if target_id in self._by_target:
                break
            await asyncio.sleep(0.01)
        else:
            raise TabGone("建了 target 但没收到 targetCreated", code="tab_gone",
                          details={"reason": "closed"})

        tab = self._by_id[self._by_target[target_id]]
        if activate:
            await self.activate(tab.id)
            # 激活之后再挤一次:谁受保护变了 —— 原来那个激活的现在可以挤了。
            await self._evict_if_needed(protect=tab.id)
        return tab

    async def close(self, tab_id: str) -> dict[str, Any]:
        """关掉。**永远至少留一个 tab** —— Chromium 关掉最后一个会连窗口一起关,
        所以先补一个 `about:blank`(api/tabs.md §3)。"""
        tab = self.get(tab_id)
        created = None
        if len(self._by_id) == 1:
            created = await self.open("about:blank", activate=False)

        with suppress(CDPError):
            await self._cdp.send("Target.closeTarget", {"targetId": tab.target_id})
        self._forget(tab_id, reason="closed")

        if created is not None:
            await self.activate(created.id)
        return {"closed": tab_id,
                "created": created.to_json(index=self.index_of(created.id),
                                           active=True) if created else None,
                "active": self._active}

    def _forget(self, tab_id: str, *, reason: str) -> None:
        tab = self._by_id.pop(tab_id, None)
        if tab is None:
            return
        self._by_target.pop(tab.target_id, None)
        self._order.remove(tab_id)
        self._retired[tab_id] = {"reason": reason, "final_url": tab.url}

        if self._active == tab_id:
            # 焦点落到邻居,而不是留个空 —— 画面上总得显示点什么
            self._active = self._order[-1] if self._order else None
            if self._active:
                asyncio.create_task(self._enforce_active())
        self._emit("tab.closed", {"id": tab_id, "active": self._active,
                                  "reason": reason, "final_url": tab.url})

    def update(self, tab_id: str, **fields: Any) -> None:
        """**只发变化的字段** —— 整条替换会让外面的 tab 条闪、丢掉滚动位置。"""
        tab = self._by_id.get(tab_id)
        if tab is None:
            return
        changed = {k: v for k, v in fields.items()
                   if getattr(tab, k, object()) != v and hasattr(tab, k)}
        if not changed:
            return
        for k, v in changed.items():
            setattr(tab, k, v)
        self._emit("tab.updated", {"id": tab_id, "changed": changed})

    # ------------------------------------------------------------- active

    async def activate(self, tab_id: str) -> TabInfo:
        """切过去。

        **我们改自己的字段,再把 Chromium 拽过来对齐**,不是反过来观测
        (api/tabs.md §5)。CDP 没有"tab 被激活了"这种事件,所以没得观测。
        """
        tab = self.get(tab_id)
        previous, self._active = self._active, tab_id
        tab.touched_at = time.time()
        await self._enforce_active()
        if previous != tab_id:
            self._emit("tab.activated", {"id": tab_id, "previous": previous})
        return tab

    async def _enforce_active(self) -> None:
        """把画面对齐到记录上。已经对着就是个空操作。"""
        if not self._active:
            return
        tab = self._by_id.get(self._active)
        if tab:
            try:
                await self._cdp.send("Target.activateTarget", {"targetId": tab.target_id})
            except CDPError as e:
                log.debug("activateTarget 没成:%s", e)

    def touch(self, tab_id: str) -> None:
        """记一笔"这个 tab 刚被操作过" —— LRU 挤谁看它。"""
        tab = self._by_id.get(tab_id)
        if tab:
            tab.touched_at = time.time()

    # --------------------------------------------------------------- 上限

    async def _evict_if_needed(self, *, protect: str | None = None) -> None:
        """超了就挤掉最不活跃的。

        三条硬规矩(api/tabs.md §3):当前激活的永远不挤(人正看着的东西不能在
        眼前消失)、正在跑动作的不挤(会让那个动作变成一半)、先建后挤
        (新建的不会被自己挤掉 —— 它刚 touch 过,LRU 天然排最后)。
        """
        while len(self._by_id) > self._tab_max:
            victim = self._pick_victim(protect)
            if victim is None:
                # 全在忙、或者只剩激活的和刚建的 —— 宁可短暂超一个,
                # 也不挤掉人正看着的或跑到一半的。
                log.warning("超了 tab 上限但没有可挤的(%d/%d)", len(self._by_id), self._tab_max)
                return
            tab = self._by_id[victim]
            final_url = tab.url
            # **先标记,再 await。**
            #
            # `Target.closeTarget` 的 await 中间会让出控制权,而 Chromium 的
            # `targetDestroyed` 事件**经常比这个响应先到**。先到的话
            # `_on_destroyed` 已经把这个 tab 清干净了,于是原来写在下面的
            # `self._order.remove(victim)` 会 `ValueError: x not in list`,
            # **紧跟其后那句 `reason="evicted"` 的事件就再也发不出去** ——
            # 表现为"被挤掉的 tab 报成了 closed",或者干脆一个事件都没有。
            #
            # 所以:谁先到都行,记账只做一次,reason 一定是 evicted。
            self._evicting.add(tab.target_id)
            try:
                with suppress(CDPError):
                    await self._cdp.send("Target.closeTarget",
                                         {"targetId": tab.target_id})
                # 事件没先到才轮到我们收尾。`_forget` 本身是幂等的。
                self._forget(victim, reason="evicted")
            finally:
                self._evicting.discard(tab.target_id)
            log.info("挤掉 %s(%s)—— 超了 %d 个上限", victim, final_url, self._tab_max)

    def _pick_victim(self, protect: str | None = None) -> str | None:
        cands = [i for i in self._order
                 if i != self._active and i != protect and i not in self._busy]
        if not cands:
            return None
        return min(cands, key=lambda i: self._by_id[i].touched_at)

    # ------------------------------------------------------------ 忙/闲

    def mark_busy(self, tab_id: str) -> None:
        self._busy.add(tab_id)

    def mark_idle(self, tab_id: str) -> None:
        self._busy.discard(tab_id)
        self.touch(tab_id)
