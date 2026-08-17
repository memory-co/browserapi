"""RTT 自适应画质 —— docs/v2/works/02-frame-protocol.md §3。

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
from dataclasses import dataclass

SLOW_MS = 725.0         # 超过就降
FAST_MS = 600.0         # 低于就升
THROTTLE_S = 8.0        # 两个方向各自的冷却
QUALITY_STEP = 20
QUALITY_FLOOR = 5
NTH_CAP = 8
WINDOW = 8              # 滑动窗口取几个样本


@dataclass
class Settings:
    quality: int
    every_nth: int

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, Settings) and self.quality == other.quality
                and self.every_nth == other.every_nth)


class Adaptor:
    """喂 RTT,吐新的 `(quality, every_nth)`;没变就返回 None。

    `lossless=True`(png)时 `quality` 不动,只抽帧。
    """

    def __init__(self, quality: int = 80, *, lossless: bool = False) -> None:
        self.ceiling = quality
        self.quality = quality
        self.every_nth = 1
        self.lossless = lossless
        self._rtts: list[float] = []
        self._last_down = 0.0
        self._last_up = 0.0

    @property
    def settings(self) -> Settings:
        return Settings(self.quality, self.every_nth)

    def feed(self, rtt_ms: float) -> Settings | None:
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
        if not self.lossless and self.quality > QUALITY_FLOOR:
            self.quality = max(QUALITY_FLOOR, self.quality - QUALITY_STEP)
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
