"""RTT 自适应画质 —— docs/v2/works/e1-wire-format.md §3。

阈值**直接取自 BrowserBox** 的 `src/zombie-lord/screenShots.js`,不是我们调的:

    RTT > 725ms  降质        RTT < 600ms  升质        两个方向各 throttle 8 秒

**先砍画质再抽帧**,顺序不能反 —— 糊一点的连续画面比清晰的卡顿画面可用得多。
人在拖拽、滚动时,连续性就是可操作性。

两个坑写在代码里:

- **png 是无损的,`quality` 对它完全无效**,所以 png 模式下只剩抽帧一个手段。
- 本机 RTT 只有几毫秒,画质会一直顶在上限 —— **想验证这套逻辑必须人为加延迟**。
"""

from __future__ import annotations

import time

from webmuxd.models import Quality

SLOW_MS = 725.0         # 超过就降
FAST_MS = 600.0         # 低于就升
THROTTLE_S = 8.0        # 两个方向各自的冷却
QUALITY_STEP = 20
#: 降到底是多少。
#:
#: BrowserBox 那边是 5,我们一开始照抄了 —— **但 q5 是马赛克,根本没法用**,
#: 而且 20 → 5 是个断崖。降质的意义是"糊一点但还能操作",不是"糊到看不清"。
#:
#: 25 不是拍的:BrowserBox 自己在 Tor 模式下就把下限压到 25
#: ([c](../docs/v2/works/c-view.md))—— 那是它认为的"还能用"的底。
#: 到底了就改抽帧,那才是链路真撑不住时该退的方向。
QUALITY_FLOOR = 25
NTH_CAP = 8
WINDOW = 8              # 滑动窗口取几个样本


class Adaptor:
    """喂 RTT,吐新的 `(quality, every_nth)`;没变就返回 None。

    `lossless=True`(png)时 `quality` 不动,只抽帧。
    """

    def __init__(self, quality: int = 80, *, lossless: bool = False,
                 floor: int = QUALITY_FLOOR) -> None:
        self.ceiling = quality
        #: 下限不能高过上限 —— 那样它会在两头之间反复横跳
        self.floor = max(1, min(int(floor), quality))
        self.quality = quality
        self.every_nth = 1
        self.lossless = lossless
        self._rtts: list[float] = []
        self._last_down = 0.0
        self._last_up = 0.0

    @property
    def settings(self) -> Quality:
        return Quality(self.quality, self.every_nth)

    def feed(self, rtt_ms: float) -> Quality | None:
        self._rtts.append(rtt_ms)
        if len(self._rtts) > WINDOW:
            del self._rtts[:-WINDOW]
        if len(self._rtts) < 3:            # 样本太少不动,免得一次抖动就降质
            return None
        avg = sum(self._rtts) / len(self._rtts)
        now = time.monotonic()

        if avg > SLOW_MS and now - self._last_down >= THROTTLE_S:
            if self._down():
                self._last_down = now
                self._rtts.clear()
                return self.settings
        elif avg < FAST_MS and now - self._last_up >= THROTTLE_S:
            if self._up():
                self._last_up = now
                self._rtts.clear()
                return self.settings
        return None

    # -------------------------------------------------------------- 两个方向

    def _down(self) -> bool:
        """**先砍画质,砍到底再抽帧。**"""
        if not self.lossless and self.quality > self.floor:
            self.quality = max(self.floor, self.quality - QUALITY_STEP)
            return True
        if self.every_nth < NTH_CAP:
            self.every_nth += 1
            return True
        return False

    def _up(self) -> bool:
        """反过来:先把帧率还回去,再还画质。"""
        if self.every_nth > 1:
            self.every_nth -= 1
            return True
        if not self.lossless and self.quality < self.ceiling:
            self.quality = min(self.ceiling, self.quality + QUALITY_STEP)
            return True
        return False
