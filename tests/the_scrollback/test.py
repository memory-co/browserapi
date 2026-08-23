"""操作日志 —— 对着 docs/v1/works/03-log.md 和 api/log.md 校。

不需要 Chromium,所以跑得快。
"""

import json
import zipfile

import pytest

from webmuxd.log import KINDS, Log, Seq


@pytest.fixture
def log(tmp_path):
    return Log(tmp_path, limit=10)


# ------------------------------------------------------------------ 类目

def test_kinds_are_a_closed_set():
    """**类目是封闭的,而且每一类都对应"有人要为它负责"。**

    v1 是三类,判据是"页面自己的变化不进日志 —— 没有人做它们"(works/03 §1.2)。
    v2 多的五类**没有推翻那条**:对话框、文件选择、权限、认证都是
    **挡住页面、等人回答**的决定点,下载是"东西落到了这台机器上" ——
    它们全都有人负责,而且是「页面为什么停住」的唯一解释
    (docs/v2/works/06 §3)。

    仍然进不来的是页面自己的变化:滚动、动画、XHR、DOM 改了 ——
    那些没有人"做",它们属于观测,不属于 scrollback。

    **`diag` 是唯一一个不属于"有人做了什么"的类**,它是"出了什么问题"。
    放进来是因为排查时**只该看一个地方**:以前诊断只进 `server.log`,
    那是整台 server 一份、不带 session id,而且和这条流没有共同的编号 ——
    最需要它的时候最找不到(CPU 打满那种情况下这条流是**空白**的,
    没有人在"做"任何事,而真相在另一份文件里)。
    """
    assert KINDS == ("action", "tab", "session", "dialog", "download",
                     "file", "permission", "auth", "diag")


def test_unknown_kind_is_rejected(log):
    with pytest.raises(ValueError):
        log.append("页面变了", tab="t_1")


def test_each_kind_round_trips(log):
    log.append("action", tab="t_3", action="click", ok=True, ms=412)
    log.append("tab", tab="t_7", event="opened", reason="page", user="human")
    log.append("session", event="chrome_restarted", restarts=1)

    kinds = [e["kind"] for e in log.read()]
    assert kinds == ["action", "tab", "session"]
    assert log.read(kind="tab")[0]["reason"] == "page"
    assert log.read(kind="session")[0]["event"] == "chrome_restarted"


# ------------------------------------------------------------------- seq

def test_seq_is_monotonic_and_shared():
    """日志和事件流**共用一个计数器** —— 拿一条日志的 seq 就能在事件流里
    找到它前后发生了什么(works/06 §5)。"""
    shared = Seq()
    assert shared.next() == 1
    assert shared.next() == 2


def test_seq_survives_restart(tmp_path):
    """重启之后接着往下发号 —— 倒退就会和历史记录撞车。"""
    a = Log(tmp_path)
    for _ in range(3):
        a.append("action", action="click")
    last = a.seq.current

    b = Log(tmp_path)          # 同一个目录重新打开
    assert b.seq.next() == last + 1


# ------------------------------------------------------------------ 筛选

def test_filters_are_just_filters(log):
    """磁盘上就一个 jsonl,所有筛选都是过滤(works/03 §1.1)。"""
    log.append("action", tab="t_1", user="claudecode", ok=True, action="click")
    log.append("action", tab="t_2", user="human", ok=False, action="click")
    log.append("action", tab="t_1", user="human", ok=True, action="type")

    assert len(log.read(tab="t_1")) == 2
    assert len(log.read(user="human")) == 2
    assert len(log.read(only="failed")) == 1
    assert log.read(only="failed")[0]["tab"] == "t_2"


def test_after_pages_forward(log):
    seqs = [log.append("action", action="click") for _ in range(5)]
    got = log.read(after=seqs[2])
    assert [e["seq"] for e in got] == seqs[3:]


def test_limit_gives_the_most_recent(log):
    for i in range(5):
        log.append("action", action=f"a{i}")
    got = log.read(limit=2)
    assert [e["action"] for e in got] == ["a3", "a4"], "limit 该给最近的,不是最早的"


# ------------------------------------------------------------------ 切割

def test_rotation_keeps_only_the_previous_roll(tmp_path):
    """满了切一刀,**只留上一刀** —— 在线记录永远在 LIMIT ~ 2×LIMIT 之间
    (works/03 §5)。"""
    log = Log(tmp_path, limit=10)
    for i in range(35):
        log.append("action", action=f"a{i}")

    assert (tmp_path / "log.jsonl").exists()
    assert (tmp_path / "log.1.jsonl").exists()
    assert not (tmp_path / "log.2.jsonl").exists(), "留多了 —— 这是 scrollback 不是归档"

    total = log.count()
    assert 10 <= total <= 20, f"在线记录 {total} 条,不在 LIMIT~2×LIMIT 之间"
    # 最新的一定还在
    assert log.read(limit=1)[0]["action"] == "a34"


def test_rotation_drops_the_shots_it_drops_records_for(tmp_path):
    """切掉的那批记录,截图一起删 —— 留着没有记录的图既占地方又没法解释。"""
    log = Log(tmp_path, limit=5)
    kept_alive = []
    for i in range(30):
        seq = log.append("action", action=f"a{i}", shot=True)
        log.shot_path(seq).write_bytes(b"fake")
        kept_alive.append(seq)

    on_disk = {int(p.stem) for p in log.shots.glob("*.webp")}
    still_logged = {e["seq"] for e in log.read(limit=0)}
    assert on_disk <= still_logged | {max(still_logged)}, \
        f"有图没记录:{sorted(on_disk - still_logged)}"
    assert len(on_disk) < 30, "一张都没删,磁盘会被撑爆"


def test_a_half_written_line_does_not_break_reading(tmp_path):
    """写到一半被杀掉,不该让整份日志读不出来。"""
    log = Log(tmp_path)
    log.append("action", action="click")
    with (tmp_path / "log.jsonl").open("a") as fh:
        fh.write('{"seq": 2, "kind": "acti')      # 半行
    log2 = Log(tmp_path)
    assert len(log2.read()) == 1


# ------------------------------------------------------------------ 打包

def test_bundle_is_self_contained(tmp_path):
    """解开双击就能看,**不依赖容器还活着**(works/03 §4)。"""
    log = Log(tmp_path)
    seq = log.append("action", tab="t_1", action="click",
                     target={"text": "提交订单"},
                     hit={"role": "button", "name": "取消订单"},
                     ok=True, after={"changed": "出现『订单已取消』"},
                     note="购物车已确认,现在下单", user="claudecode", shot=True)
    log.shot_path(seq).write_bytes(b"fake-image")

    z = zipfile.ZipFile(__import__("io").BytesIO(log.bundle()))
    names = z.namelist()
    assert "log.jsonl" in names and "index.html" in names
    assert f"shots/{seq:06d}.webp" in names

    html = z.read("index.html").decode()
    assert "取消订单" in html and "购物车已确认" in html
    assert "出现『订单已取消』" in html


def test_bundle_can_be_narrowed_to_one_tab(tmp_path):
    log = Log(tmp_path)
    log.append("action", tab="t_1", action="click")
    log.append("action", tab="t_2", action="click")
    z = zipfile.ZipFile(__import__("io").BytesIO(log.bundle(tab="t_2")))
    lines = [json.loads(l) for l in z.read("log.jsonl").decode().splitlines() if l]
    assert {e["tab"] for e in lines} == {"t_2"}


def test_offline_html_escapes_page_content(tmp_path):
    """页面内容会进日志,里面可能有 `<script>` —— 离线页不能被它注入。"""
    log = Log(tmp_path)
    log.append("action", action="click",
               target={"text": "<script>alert(1)</script>"},
               after={"changed": "<img onerror=x>"})
    html = zipfile.ZipFile(__import__("io").BytesIO(log.bundle())).read("index.html").decode()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ---------------------------------------------------------------- note 那列

def test_note_rides_along_with_the_action(log):
    """`note` 是这套东西的核心:webmuxd 不产生思考,但它提供一个
    思考与后果对齐的存放位置(works/03 §2)。"""
    log.append("action", action="click", target={"text": "提交订单"},
               hit={"role": "button", "name": "取消订单"},
               note="购物车里已有一张票,现在去确认支付", ok=True)
    e = log.read()[0]
    assert e["note"].startswith("购物车")
    assert e["hit"]["name"] == "取消订单" and e["target"]["text"] == "提交订单", \
        "target 和 hit 要分开摆,才看得出是认错了元素还是页面变了"


def test_none_fields_are_not_written(log):
    """没有的字段就别写进去 —— 日志一行一条,塞满 null 没意义。"""
    log.append("action", action="click", note=None, user=None)
    assert "note" not in log.read()[0]
