"""pytest 全局夹具：测试隔离与环境准备。

本文件解决两个核心问题：

1. app/selfcheck.py 的模型 pin（_MODEL_CACHE / _WEIGHTS_PIN）是**进程级全局单例**，
   首次成功加载后即固定到进程重启为止。测试之间共享这一状态会产生顺序污染——
   例如 test_selfcheck_valid_image 先加载了权重，随后 test_selfcheck_missing_weights
   把 HELMET_GUARD_SELFCHECK_WEIGHTS 指向一个不存在的文件，但因为模型已 pin 在内存里，
   model_status() 仍返回 ready=True，接口返回 200 而不是预期的 503。

   这不是产品缺陷（pin 本身是刻意设计，避免检测中途换模型），而是测试隔离缺陷。
   因此这里提供 autouse 夹具，在每个测试前后清理模型 pin 状态，使每个测试都从
   "未加载模型" 的干净状态开始。

2. 本机 %TEMP% 下的 pytest-of-<user> 目录 ACL 异常（拒绝访问），pytest 内置
   tmp_path 工厂无法在其中建目录，所有用到 tmp_path 的测试会以 PermissionError
   失败。这里覆盖内置 tmp_path 夹具，改指向项目内可写目录。
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import PROJECT_ROOT

# 会在测试中被 monkeypatch 修改的环境变量，测试后必须还原，
# 否则会污染后续测试的默认配置（尤其是 HELMET_GUARD_DB / HELMET_GUARD_MODE）。
_MANAGED_ENV_VARS = (
    "HELMET_GUARD_MODE",
    "HELMET_GUARD_DB",
    "HELMET_GUARD_WEIGHTS",
    "HELMET_GUARD_SELFCHECK_WEIGHTS",
    "HELMET_GUARD_HEARTBEAT_EXPIRE",
    "HELMET_GUARD_ALERTS_ENABLED",
)


def _reset_model_pin() -> None:
    """清空 selfcheck 的进程级模型 pin，让下一个需要模型的测试重新加载。

    刻意只重置 selfcheck 的缓存：vision.py / tracks.py 等纯函数模块无全局状态。
    """
    from app import selfcheck

    selfcheck._MODEL_CACHE.update({"path": "", "model": None, "names": {}, "version": ""})
    selfcheck._WEIGHTS_PIN.update({"path": ""})


def pytest_configure(config: pytest.Config) -> None:
    """把临时目录根重定向到项目内可写目录。

    原因：本机 %TEMP% 下的 pytest-of-<user> 目录 ACL 异常（拒绝访问），
    pytest 的 TempPathFactory.getbasetemp() 在该目录下 mkdir 会抛
    PermissionError，所有用到 tmp_path 的测试随之失败。

    机制：pytest 在 getbasetemp() 里优先读取环境变量 PYTEST_DEBUG_TEMPROOT
    作为临时根。这里在 pytest_configure 阶段设置它——早于
    TempPathFactory.getbasetemp() 的首次调用，因此全局生效。
    """
    temproot = PROJECT_ROOT / ".pytest_tmp"
    try:
        temproot.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    os.environ["PYTEST_DEBUG_TEMPROOT"] = str(temproot)


@pytest.fixture(autouse=True)
def _isolate_model_pin() -> Iterator[None]:
    """每个测试前后重置模型 pin，保证测试顺序无关。

    用 autouse 而非显式声明：模型 pin 是全局副作用，任何用到 app.selfcheck 的
    测试都可能被它影响，显式声明容易漏。
    """
    _reset_model_pin()
    yield
    _reset_model_pin()


@pytest.fixture(autouse=True)
def _restore_env() -> Iterator[None]:
    """还原被 monkeypatch 改动的环境变量，避免跨测试污染。"""
    saved = {name: os.environ.get(name) for name in _MANAGED_ENV_VARS}
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """覆盖 pytest 内置 tmp_path：改用项目内可写目录。

    保留此覆盖作为兜底：即便 pytest_configure 中的 basetemp 注入因版本差异
    未生效，本夹具仍会把临时目录重定向到项目内 .pytest_tmp。

    覆盖内置夹具是 pytest 官方支持的方式（同名夹具优先于内置）。
    """
    return tmp_path_factory.mktemp("t", numbered=True)


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """每个测试独立的临时 SQLite 文件路径（尚未创建，由调用方决定建库时机）。"""
    return tmp_path / "test.db"


@pytest.fixture
def client(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    """FastAPI TestClient，绑定到独立的临时数据库。

    lifespan 内建表：与生产启动流程一致，保证查询接口不会触发建库副作用。
    """
    from fastapi.testclient import TestClient

    from app import main as main_mod

    monkeypatch.setenv("HELMET_GUARD_DB", str(tmp_db))
    monkeypatch.setenv("HELMET_GUARD_MODE", "demo")
    importlib.reload(main_mod)

    with TestClient(main_mod.app) as test_client:
        yield test_client
