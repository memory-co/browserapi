"""重新生成对拍用的 fixture。**Python 是这两份的权威。**

    python -m tests.two_implementations.regen

生成完记得去 `webmuxjs/client/` 跑 `npm test` —— 那边会跟着红,
那正是"两边一起红"该有的样子。
"""

import json

from tests.two_implementations.test import FIX, GENERATED

for name, make in GENERATED.items():
    (FIX / name).write_text(
        json.dumps(make(), ensure_ascii=False, indent=2) + "\n")
    print("写了", name)
