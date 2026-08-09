"""`webmuxd install` 和环境记录 —— 对着 docs/v1/cli/install.md 校。

install 只回答两个问题:**docker 能用吗、这个网络环境拉得到那个镜像吗**。
它不 build、不预拉。
"""

import io
import json

import pytest

from webmuxd import env, runtime as rt
from webmuxd.cli.install import install
from webmuxd.errors import RuntimeUnavailable
from webmuxd.runtime.container import ContainerRuntime
from webmuxd.runtime.process import ProcessRuntime


@pytest.fixture
def record_file(tmp_path, monkeypatch):
    p = tmp_path / ".webmuxd.json"
    monkeypatch.setenv("WEBMUXD_ENV_FILE", str(p))
    return p


@pytest.fixture
def fake_probe(monkeypatch):
    """把 install 里所有 shell 出去的动作换成可控的假货。"""
    state = {"which": "/usr/bin/docker", "version": "29.7.2", "reachable": True}

    monkeypatch.setattr("webmuxd.cli.install.shutil.which",
                        lambda n: state["which"])
    monkeypatch.setattr("webmuxd.cli.install._run",
                        lambda args: state["version"])
    monkeypatch.setattr("webmuxd.cli.install._reachable",
                        lambda d, i: state["reachable"])
    return state


# ------------------------------------------------------------------ 记录

def test_no_record_is_not_an_error(record_file):
    """**没装过也能用** —— install 省的是重复开销,不是"必须先装"
    (install.md §5)。"""
    assert env.load() is None
    assert set(rt.detect()) == {"container", "process", "remote"}
    assert rt.default() in ("container", "process", "remote")


def test_a_record_from_the_future_is_ignored(record_file):
    """格式变了老记录读不动 —— **当没有记录重新探**,而不是猜字段。"""
    record_file.write_text(json.dumps({"version": 999, "docker": "/x"}))
    assert env.load() is None
    assert env.get("docker") is None


def test_garbage_is_ignored_not_crashed_on(record_file):
    record_file.write_text("{ 半个文件")
    assert env.load() is None


def test_save_then_load_round_trips(record_file):
    env.save({"docker": "/usr/bin/docker",
              "default_container": "kasmweb/chromium:1.18.0"})
    rec = env.load()
    assert rec["docker"] == "/usr/bin/docker"
    assert rec["at"].endswith("Z"), "得记下这是什么时候探的"
    assert rec["version"] == env.FORMAT_VERSION


def test_a_key_with_no_value_is_left_out_not_written_empty(record_file):
    """**键在 = 探到了,键不在 = 没探到。** 留个空值等于留个说不清的状态。"""
    env.save({"docker": "/usr/bin/docker", "default_container": None})
    assert "default_container" not in env.load()
    assert env.get("default_container") is None


# ------------------------------------------------------------------ 探测

def test_install_records_docker_and_the_image(record_file, fake_probe):
    out = io.StringIO()
    rec = install(out=out)

    assert rec["docker"] == "/usr/bin/docker"
    assert rec["docker_version"] == "29.7.2"
    assert rec["default_container"] == "kasmweb/chromium:1.18.0"
    assert env.load()["default_container"] == rec["default_container"]
    assert "记录写到" in out.getvalue()


def test_install_is_idempotent(record_file, fake_probe):
    """再跑一次就是重新探一遍 —— 所以"检查"和"安装"是同一个命令。"""
    a = install(out=io.StringIO())
    b = install(out=io.StringIO())
    assert a["default_container"] == b["default_container"]


def test_install_never_builds_and_never_pulls(record_file, monkeypatch):
    """**探测不该顺手做一件 4 GB 的事。** 只问拉不拉得到。"""
    calls = []

    class R:
        returncode, stdout, stderr = 0, "ok", ""

    def fake(args, **kw):
        calls.append(args)
        return R()

    monkeypatch.setattr("webmuxd.cli.install.shutil.which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr("webmuxd.cli.install.subprocess.run", fake)
    install(out=io.StringIO())

    verbs = {a[1] for a in calls if len(a) > 1}
    assert "pull" not in verbs, "install 去拉镜像了"
    assert "build" not in verbs, "install 去 build 镜像了"


def test_an_unreachable_image_leaves_the_key_out(record_file, fake_probe):
    """**不记一个拉不下来的名字。** 键不在,就是"你得自己填"(install.md §2)。"""
    fake_probe["reachable"] = False
    out = io.StringIO()
    rec = install(out=out)

    assert "default_container" not in rec
    assert env.get("default_container") is None
    assert "--image" in out.getvalue(), "得告诉人怎么自己指一个"


def test_missing_docker_does_not_crash_the_command(record_file, monkeypatch):
    """探不到不让整条命令失败 —— 记下来就是了(install.md §2)。"""
    monkeypatch.setattr("webmuxd.cli.install.shutil.which", lambda _n: None)
    rec = install(out=io.StringIO())
    assert not rec.get("docker_version")
    assert "default_container" not in rec, "docker 都没有,还记镜像"
    assert rt.default() != "container", "没 docker 还把它当默认"


# ------------------------------------------------- 记录被用起来了没有

def test_detect_reads_the_record_instead_of_probing(record_file, monkeypatch):
    """**信记录,不重探** —— 每次都探等于 install 白做(install.md §4)。"""
    env.save({"docker": "/usr/bin/docker",
              "default_container": "kasmweb/chromium:1.18.0"})

    def boom(*a, **k):
        raise AssertionError("有记录还去 shell 出去探了")

    monkeypatch.setattr("webmuxd.runtime.container.subprocess.run", boom)
    assert rt.detect()["container"] is True
    assert rt.default() == "container"


def test_container_runtime_takes_docker_and_image_from_the_record(record_file):
    env.save({"docker": "/opt/docker", "default_container": "me/custom:9"})
    impl = ContainerRuntime()
    assert impl.docker == "/opt/docker" and impl.image == "me/custom:9"
    assert impl.available()[0] is True


def test_what_the_caller_says_beats_the_record(record_file):
    """记录是机器的事实,**不是你的选择** —— 传进来的赢。"""
    env.save({"docker": "/opt/docker", "default_container": "me/custom:9"})
    assert ContainerRuntime(image="other/img:2").image == "other/img:2"


def test_a_stale_record_says_to_rerun_install(record_file, monkeypatch):
    """**记录会撒谎** —— 按它去起,起不来就报错并让人重跑(install.md §4)。"""
    monkeypatch.setenv("WEBMUXD_CHROMIUM", "/nope/chromium")
    with pytest.raises(RuntimeUnavailable) as ei:
        ProcessRuntime().start("x", api_port=1, vnc_port=2)
    assert "webmuxd install" in str(ei.value) or "webmuxd install" in ei.value.hint


def test_stale_hint_names_the_command():
    assert "webmuxd install" in env.stale_hint("chromium 在 /x")
