"""Python lib —— 主体在这儿(docs/v1/sdk/)。

    web  = Webmuxd()
    sess = web.session(id="work", port=7900)
    tab  = sess.open("https://shop.example.com")
    tab.click("登录")
"""

from webmuxd.client.manager import Webmuxd          # noqa: F401
from webmuxd.client.session import Session          # noqa: F401
from webmuxd.client.tab import ActResult, Tab       # noqa: F401
from webmuxd.client.observation import Element, Observation  # noqa: F401

__all__ = ["Webmuxd", "Session", "Tab", "ActResult", "Observation", "Element"]
