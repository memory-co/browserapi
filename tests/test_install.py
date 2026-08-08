"""`webmuxd install` 和环境记录 —— 对着 docs/v1/cli/install.md 校。"""

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


# ------------------------------------------------------------------ 记录

def test_no_record_is_not_an_error(record_file):
    """**没装过也能用** —— install 省的是重复开销,不是"必须先装"
    (install.md §5)。"""
    assert env.load() is None
    assert set(rt.detect()) == {"container", "process", "remote"}
    assert rt.default() in ("container", "process", "remote")


def test_a_record_from_the_future_is_ignored(record_file):
    """格式变了老记录读不动 —— **当没有记录重新探**,而不是猜字段。"""
    record_file.write_text(json.dumps({"version": 999, "runtimes": {}}))
    assert env.load() is None


def test_garbage_is_ignored_not_crashed_on(record_file):
    record_file.write_text("{ 半个文件")
    assert env.load() is None


def test_save_then_load_round_trips(record_file):
    env.save({"webmuxd": "0.1.0", "runtimes": {"process": {"ok": True}},
              "default_runtime": "process"})
    rec = env.load()
    assert rec["runtimes"]["process"]["ok"] is True
    assert rec["at"].endswith("Z"), "得记下这是什么时候探的"
    assert rec["version"] == env.FORMAT_VERSION


# ------------------------------------------------------------------ 探测

def test_install_writes_what_it_found(record_file):
    out = io.StringIO()
    rec = install(pull=False, out=out)

    assert rec["runtimes"].keys() >= {"container", "process", "remote"}
    assert env.load()["default_runtime"] == rec["default_runtime"]
    text = out.getvalue()
    assert "记录写到" in text and "可用的 runtime" in text


def test_install_is_idempotent(record_file):
    """再跑一次就是重新探一遍 —— 所以"检查"和"安装"是同一个命令。"""
    a = install(pull=False, out=io.StringIO())
    b = install(pull=False, out=io.StringIO())
    assert a["runtimes"]["process"]["ok"] == b["runtimes"]["process"]["ok"]


def test_missing_docker_does_not_fail_the_whole_install(record_file, monkeypatch):
    """**一台能用 process 的机器不该因为没装 docker 就装不上**(install.md §2)。"""
    monkeypatch.setattr("webmuxd.cli.install.shutil.which",
                        lambda n: None if n == "docker" else f"/usr/bin/{n}")
    rec = install(pull=False, out=io.StringIO())
    assert rec["runtimes"]["container"]["ok"] is False
    assert rec["runtimes"]["container"]["why"]
    assert rec["default_runtime"] != "container", "没 docker 还把它当默认"


def test_a_failed_pull_is_recorded_not_fatal(record_file, monkeypatch):
    """拉不到镜像**不代表 docker 不能用** —— 记下来,别把整条命令判死。"""
    monkeypatch.setattr("webmuxd.cli.install.shutil.which", lambda _n: "/usr/bin/docker")
    # docker 在、版本问得到,但本机还没有那个镜像
    monkeypatch.setattr("webmuxd.cli.install._run",
                        lambda args: None if "inspect" in args else "29.0.0")

    class R:
        returncode, stdout, stderr = 1, "", "no such image"
    monkeypatch.setattr("webmuxd.cli.install.subprocess.run", lambda *a, **k: R())

    rec = install(out=io.StringIO())
    c = rec["runtimes"]["container"]
    assert c["ok"] is True, "docker 通着,只是镜像没拉到"
    assert c["image_pulled"] is False and c["image_why"]


def test_no_vnc_is_written_down_not_hidden(record_file, monkeypatch):
    """有 API 没画面仍然有用,但**假装有画面比没画面更糟**。"""
    monkeypatch.setattr(
        "webmuxd.cli.install.shutil.which",
        lambda n: "/usr/bin/chromium" if n.startswith("chromium") else None)
    monkeypatch.setattr("webmuxd.cli.install._run", lambda args: "Chromium 139")
    rec = install(pull=False, out=io.StringIO())
    p = rec["runtimes"]["process"]
    assert p["ok"] is True and p["vnc"] is None
    assert any("没有画面" in n for n in p["notes"])


# ------------------------------------------------- 记录被用起来了没有

def test_detect_reads_the_record_instead_of_probing(record_file, monkeypatch):
    """**信记录,不重探** —— 每次都探等于 install 白做(install.md §4)。"""
    env.save({"runtimes": {"container": {"ok": True}, "process": {"ok": False},
                           "remote": {"ok": True}},
              "default_runtime": "container"})

    def boom(*a, **k):
        raise AssertionError("有记录还去 shell 出去探了")

    monkeypatch.setattr("webmuxd.runtime.container.subprocess.run", boom)
    assert rt.detect() == {"container": True, "process": False, "remote": True}
    assert rt.default() == "container"


def test_container_runtime_takes_docker_and_image_from_the_record(record_file):
    env.save({"runtimes": {"container": {"ok": True, "docker": "/opt/docker",
                                         "image": "me/custom:9"}},
              "default_runtime": "container"})
    impl = ContainerRuntime()
    assert impl.docker == "/opt/docker" and impl.image == "me/custom:9"
    assert impl.available()[0] is True


def test_a_stale_record_says_to_rerun_install(record_file):
    """**记录会撒谎** —— 按它去起,起不来就报错并让人重跑(install.md §4)。"""
    env.save({"runtimes": {"process": {"ok": True,
                                       "chromium": "/nope/chromium"}},
              "default_runtime": "process"})
    with pytest.raises(RuntimeUnavailable) as ei:
        ProcessRuntime().start("x", api_port=1, vnc_port=2)
    assert "webmuxd install" in str(ei.value) or "webmuxd install" in ei.value.hint


def test_stale_hint_names_the_command():
    assert "webmuxd install" in env.stale_hint("chromium 在 /x")
