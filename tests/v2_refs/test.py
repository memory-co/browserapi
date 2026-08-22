"""v2 · `@e1` 这个号的规矩。

**不起浏览器** —— 这一条管的是号本身的语义,那部分是纯数据
([`models.RefTable`](../../webmuxd/models.py))。
端到端那条在 [v2_cli_simple](../v2_cli_simple/)。

规矩只有一条,但它是这个设计的全部理由:**号只增不重用。**
重用省事,但它把"拿着过期的号去点"从一个**报错**变成了一次**点错东西**。
"""

import pytest

from webmuxd.exceptions import NotFound
from webmuxd.models import Element, Locator, RefTable


def els(*names: str, start: int = 100) -> list[Element]:
    return [Element(id=i, role="button", name=n, backend_node_id=start + i)
            for i, n in enumerate(names, start=1)]


def test_refs_are_handed_out_one_by_one_from_e1():
    t = RefTable()
    a = els("登录", "注册")
    t.assign(a, "t_1")
    assert [e.ref for e in a] == ["e1", "e2"]
    assert t.get("e1", "t_1").name == "登录"
    assert t.get("@e2", "t_1").name == "注册", "带不带 @ 都认"


def test_second_snapshot_does_not_restart_at_e1():
    """**这一条是整个设计。**

    agent-browser 那边第二次 `@e1` 指着另一个元素;我们不跟 ——
    拿旧号去点,要么报错,要么什么都不会发生,**不能是"点到了别的"**。
    """
    t = RefTable()
    first = els("登录")
    t.assign(first, "t_1")

    second = els("退出")                 # 页面变了,完全是另一批元素
    t.assign(second, "t_1")

    assert second[0].ref == "e2", "该接着发,不该又是 e1"
    assert t.get("e1", "t_1").name == "登录", "老号还指着老那个,没被顶掉"


def test_unknown_ref_says_which_kind_of_unknown():
    """**三种失败要给三句不一样的话** —— 该做的事不一样。"""
    t = RefTable()
    with pytest.raises(NotFound, match="还没 snapshot 过"):
        t.get("e1", "t_1")

    t.assign(els("登录"), "t_1")
    with pytest.raises(NotFound, match="现在发到 @e1"):
        t.get("e9", "t_1")               # 号抄错了 —— 告诉他发到哪儿了

    with pytest.raises(NotFound, match="是 t_1 上的号"):
        t.get("e1", "t_2")               # 换 tab 了


def test_closing_a_tab_frees_refs_but_never_rewinds():
    """**`next_n` 不回退。** 回退就等于重用,那正是要防的事。"""
    t = RefTable()
    t.assign(els("甲"), "t_1")
    t.assign(els("乙"), "t_2")
    t.forget("t_1")

    assert "e1" not in t.by_id and "e2" in t.by_id
    fresh = els("丙")
    t.assign(fresh, "t_1")
    assert fresh[0].ref == "e3", "腾出来的号不能再发一遍"


def test_no_ref_for_elements_without_a_handle():
    """`backend_node_id` 是空的就没法认回来 —— **发个认不回来的号是骗人**。"""
    t = RefTable()
    a = [Element(id=1, role="button", name="影子", backend_node_id=None)]
    t.assign(a, "t_1")
    assert a[0].ref == "" and not t.by_id


def test_ref_is_a_locator_and_not_the_same_as_nth():
    assert "ref" in Locator.KEYS
    assert Locator(ref="e7").to_json() == {"ref": "e7"}
    # nth 是"这几个同名的里第几个",只在这一次匹配里成立
    assert Locator(text="登录", nth=1).to_json() == {"text": "登录", "nth": 1}


def test_as_line_prefers_the_ref_over_the_index():
    assert Element(id=3, role="button", name="登录", ref="e7").as_line().startswith("@e7")
    assert Element(id=3, role="button", name="登录").as_line().startswith("[3]")
