"""异常树 —— 对着 docs/v1/sdk/README.md §5 和 api/README.md §4 校。"""

import pytest

from webmuxd import exceptions as E


def test_every_wire_code_has_a_class():
    """api/README §4 + api/server.md §5 列的码,一个都不能少。"""
    documented = {
        "not_found", "not_clickable", "timeout", "nav_failed", "tab_gone",
        "busy", "busy_human", "read_only", "chrome_gone", "blocked_url",
        "bad_request", "session_not_found", "session_exists",
        "runtime_unavailable", "port_in_use", "session_dead",
    }
    assert documented == set(E._BY_CODE)


@pytest.mark.parametrize(
    "code,base",
    [
        # 「你能自愈」
        ("not_found", E.ActionError), ("not_clickable", E.ActionError),
        ("timeout", E.ActionError), ("nav_failed", E.ActionError),
        ("tab_gone", E.ActionError), ("busy", E.ActionError),
        ("busy_human", E.ActionError),
        # 「该告警」
        ("chrome_gone", E.PlatformError), ("session_dead", E.PlatformError),
        ("runtime_unavailable", E.PlatformError), ("port_in_use", E.PlatformError),
        # 「改代码」
        ("bad_request", E.UsageError), ("blocked_url", E.UsageError),
        ("read_only", E.UsageError), ("session_exists", E.UsageError),
        ("session_not_found", E.UsageError),
    ],
)
def test_the_triage_split_holds(code, base):
    """这个二分是给调用方用的:except ActionError 是重试循环,
    except PlatformError 是告警。分错了整个语义就塌了。"""
    assert issubclass(E._BY_CODE[code], base)


def test_not_found_carries_candidates():
    e = E.from_response(
        {"error": {"code": "not_found", "message": "找不到「提交订单」",
                   "details": {"candidates": [{"role": "button", "name": "提交订单(2)"}]}}},
        404,
    )
    assert isinstance(e, E.NotFound)
    assert e.candidates[0]["name"] == "提交订单(2)"


def test_not_found_without_details_still_gives_a_list():
    """没候选时也得是空列表 —— 调用方直接 for 它,不该先判 None。"""
    assert E.NotFound("x").candidates == []


def test_tab_gone_tells_evicted_from_closed():
    """被挤掉不是任何人的意图,调用方要分得清(api/tabs.md §3)。"""
    e = E.from_response(
        {"error": {"code": "tab_gone", "message": "t_4 被挤掉了",
                   "details": {"reason": "evicted", "final_url": "https://help.example.com"}}},
        404,
    )
    assert e.reason == "evicted"
    assert e.final_url == "https://help.example.com"


def test_busy_human_carries_retry_after():
    e = E.from_response(
        {"error": {"code": "busy_human", "message": "人正在操作",
                   "details": {"retry_after_ms": 2400}}}, 409)
    assert isinstance(e, E.BusyHuman) and e.retry_after_ms == 2400


def test_unknown_code_falls_back_by_status_not_keyerror():
    """新加的码即使还没建类,也要以基类形式抛出来(sdk/README §5)。"""
    e = E.from_response({"error": {"code": "brand_new_thing", "message": "?"}}, 503)
    assert type(e) is E.PlatformError
    assert e.code == "brand_new_thing"

    e = E.from_response({"error": {"code": "also_new", "message": "?"}}, 400)
    assert type(e) is E.UsageError


def test_malformed_body_still_yields_an_exception():
    """服务端吐了个不成形状的东西,调用方也不该拿到 TypeError。"""
    for body in (None, "boom", {}, {"error": "just_a_string"}, {"error": {"details": 7}}):
        e = E.from_response(body, 500)
        assert isinstance(e, E.WebmuxdError)
        assert e.details == {}


def test_raise_for_response_is_quiet_on_success():
    assert E.raise_for_response({"ok": True}, 200) is None
    with pytest.raises(E.BlockedURL):
        E.raise_for_response({"error": {"code": "blocked_url", "message": "no"}}, 400)


def test_str_is_readable():
    e = E.NotFound("找不到「提交」", code="not_found")
    assert str(e) == "not_found: 找不到「提交」"
