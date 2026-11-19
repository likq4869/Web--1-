"""分层检查：禁止 domain 碰 I/O、禁止路由层直写 SQL。

规则：
  R1: app/domain/** 不得 import sqlalchemy / services / repositories / Session / requests。
  R2: app/api/** 不得出现 session.execute / session.query / select(
      / session.commit / session.rollback。
      事务必须下沉到服务层（B-3），SQL 必须下沉到仓储层（B-4）。

用法：python scripts/check_layering.py
退出码 0 表示通过，非 0 表示违规并打印明细。
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = PROJECT_ROOT / "app"

# R1：domain 层禁用的导入片段（正则，匹配 import 行）。
_DOMAIN_BANNED = (
    re.compile(r"^\s*(import|from)\s+sqlalchemy\b"),
    re.compile(r"^\s*(import|from)\s+app\.services\b"),
    re.compile(r"^\s*(import|from)\s+app\.repositories\b"),
    re.compile(r"^\s*(import|from)\s+requests\b"),
    re.compile(r"\bSession\b"),
)

# R2：api 层禁用的调用片段（正文搜索，排除注释行）。
_API_BANNED = (
    "session.execute",
    "session.query",
    "session.commit",
    "session.rollback",
    "select(",
)


def _strip_comment(line: str) -> str:
    """去掉行尾注释，避免注释里的示例触发误报。"""
    # 简单处理：# 之前的内容；字符串里含 # 的极少，检查脚本可接受。
    if "#" in line:
        return line.split("#", 1)[0]
    return line


def check_domain() -> list[str]:
    """检查 domain 层纯度，返回违规明细。"""
    violations: list[str] = []
    domain_root = APP_ROOT / "domain"
    if not domain_root.is_dir():
        return ["app/domain/ 目录不存在"]
    for path in sorted(domain_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            code = _strip_comment(line)
            for pattern in _DOMAIN_BANNED:
                if pattern.search(code):
                    rel = path.relative_to(PROJECT_ROOT).as_posix()
                    violations.append(f"R1 {rel}:{lineno}: {line.strip()}")
                    break
    return violations


def check_api() -> list[str]:
    """检查路由层去 SQL/去事务，返回违规明细。"""
    violations: list[str] = []
    api_root = APP_ROOT / "api"
    if not api_root.is_dir():
        return ["app/api/ 目录不存在"]
    for path in sorted(api_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            code = _strip_comment(line)
            for banned in _API_BANNED:
                if banned in code:
                    rel = path.relative_to(PROJECT_ROOT).as_posix()
                    violations.append(f"R2 {rel}:{lineno}: {line.strip()}")
                    break
    return violations


def main() -> int:
    """执行全部检查并报告。"""
    violations = check_domain() + check_api()
    if violations:
        print(f"分层检查失败，共 {len(violations)} 处违规：")
        for item in violations:
            print("  " + item)
        return 1
    print("分层检查通过：domain 零 I/O，api 零 SQL/零事务。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
