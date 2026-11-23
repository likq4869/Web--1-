"""导出可视化接口文档：生成自包含单文件 HTML。

职责：从运行中的 FastAPI 应用导出 OpenAPI 规格，渲染为离线可双击打开的
     单文件 HTML 接口文档（目录树 + 参数表 + 请求/响应示例）。
依赖：app.main.app、fastapi.openapi.utils。
边界：只读导出，不写业务库；产物写入 `docs文档/`。

用法：
    python scripts/export_api_docs.py
    python scripts/export_api_docs.py --open      # 导出后用默认浏览器打开
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import webbrowser
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "docs文档" / "接口文档.html"
TEMPLATE_PATH = Path(__file__).resolve().parent / "api_docs_template.html"

METHOD_ORDER = ["get", "post", "put", "patch", "delete", "head", "options"]
METHOD_LABEL = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
    "head": "HEAD",
    "options": "OPTIONS",
}


def _resolve_ref(ref: str, components: dict[str, Any]) -> dict[str, Any]:
    """解析 `$ref` 指向的组件 schema。

    Args:
        ref: 形如 `#/components/schemas/Name` 的引用。
        components: OpenAPI components 字典。

    Returns:
        目标 schema；引用不存在时返回空字典。
    """
    if not ref.startswith("#/components/"):
        return {}
    node: Any = components
    for part in ref.removeprefix("#/").split("/"):
        if not isinstance(node, dict) or part not in node:
            return {}
        node = node[part]
    return node if isinstance(node, dict) else {}


def _schema_type(schema: dict[str, Any], components: dict[str, Any]) -> str:
    """提取 schema 的可读类型名。

    Args:
        schema: schema 字典。
        components: OpenAPI components 字典。

    Returns:
        类型名文本；无法判定时返回空字符串。
    """
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            parts = [_schema_type(s, components) for s in schema[key]]
            joined = " | ".join(p for p in parts if p)
            return joined or "any"
    if "type" in schema:
        kind = schema["type"]
        if kind == "array":
            inner = _schema_type(schema.get("items", {}), components)
            return f"array<{inner}>" if inner else "array"
        if kind == "object" and "additionalProperties" in schema:
            inner = _schema_type(schema["additionalProperties"], components)
            return f"object<{inner}>" if inner else "object"
        return str(kind)
    if "enum" in schema:
        return "enum"
    if "properties" in schema:
        return "object"
    return ""


def _example_for(schema: dict[str, Any], components: dict[str, Any], depth: int = 0) -> Any:
    """依据 schema 构造示例值。

    Args:
        schema: schema 字典。
        components: OpenAPI components 字典。
        depth: 递归深度，防止循环引用导致无限递归。

    Returns:
        示例值（dict / list / 标量）。
    """
    if depth > 6:
        return None
    if "$ref" in schema:
        return _example_for(_resolve_ref(schema["$ref"], components), components, depth + 1)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return _example_for(schema[key][0], components, depth + 1)
    if "allOf" in schema:
        merged: dict[str, Any] = {}
        for part in schema["allOf"]:
            value = _example_for(part, components, depth + 1)
            if isinstance(value, dict):
                merged.update(value)
        return merged
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        result: dict[str, Any] = {}
        for name, prop in (schema.get("properties") or {}).items():
            result[name] = _example_for(prop, components, depth + 1)
        return result
    if kind == "array":
        item = schema.get("items", {})
        return [_example_for(item, components, depth + 1)]
    if kind == "integer":
        return 0
    if kind == "number":
        return 0
    if kind == "boolean":
        return True
    if kind == "string":
        fmt = schema.get("format")
        if fmt == "date-time":
            return "2026-01-01T00:00:00Z"
        if fmt == "date":
            return "2026-01-01"
        if fmt == "binary":
            return "<binary>"
        return "string"
    return None


def _collect_endpoints(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """把 OpenAPI 规格打平为接口列表。

    Args:
        schema: OpenAPI 规格字典。

    Returns:
        接口条目列表，每项含 tag / method / path / summary / description / operation。
    """
    endpoints: list[dict[str, Any]] = []
    for path, operations in schema.get("paths", {}).items():
        for method, operation in operations.items():
            if method not in METHOD_ORDER:
                continue
            tags = operation.get("tags") or ["未分组"]
            endpoints.append(
                {
                    "tag": tags[0],
                    "method": method,
                    "method_label": METHOD_LABEL.get(method, method.upper()),
                    "path": path,
                    "summary": operation.get("summary") or "",
                    "description": operation.get("description") or "",
                    "deprecated": bool(operation.get("deprecated")),
                    "operation": operation,
                }
            )
    endpoints.sort(key=lambda e: (e["tag"], METHOD_ORDER.index(e["method"]), e["path"]))
    return endpoints


def _anchor_of(method: str, path: str) -> str:
    """生成接口的 HTML 锚点 ID。

    Args:
        method: HTTP 方法。
        path: 接口路径。

    Returns:
        锚点 ID（不含 `#`）。
    """
    return f"{method}-{path}".replace("/", "-").replace("{", "").replace("}", "")


def _render_params(operation: dict[str, Any], components: dict[str, Any]) -> str:
    """渲染参数表。

    Args:
        operation: OpenAPI 操作对象。
        components: OpenAPI components 字典。

    Returns:
        参数表的 HTML 片段。
    """
    params = operation.get("parameters") or []
    if not params:
        return ""
    rows: list[str] = []
    for param in params:
        schema = param.get("schema") or {}
        required = "是" if param.get("required") else "否"
        default = schema.get("default")
        default_text = ""
        if default is not None:
            default_text = f"，默认 <code>{html.escape(str(default))}</code>"
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(param.get('name', ''))}</code></td>"
            f"<td>{html.escape(param.get('in', ''))}</td>"
            f"<td><code>{html.escape(_schema_type(schema, components) or '—')}</code></td>"
            f"<td>{required}</td>"
            f"<td>{html.escape(param.get('description', ''))}{default_text}</td>"
            "</tr>"
        )
    return (
        '<h4 class="sec-title">路径 / 查询参数</h4>'
        '<div class="tbl-wrap"><table class="tbl">'
        "<thead><tr><th>名称</th><th>位置</th><th>类型</th><th>必填</th><th>说明</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_request_body(operation: dict[str, Any], components: dict[str, Any]) -> str:
    """渲染请求体说明与示例。

    Args:
        operation: OpenAPI 操作对象。
        components: OpenAPI components 字典。

    Returns:
        请求体 HTML 片段。
    """
    body = operation.get("requestBody")
    if not body:
        return ""
    content = body.get("content") or {}
    if not content:
        return ""
    parts: list[str] = ['<h4 class="sec-title">请求体</h4>']
    for media_type, media in content.items():
        schema = media.get("schema") or {}
        required = "（必填）" if body.get("required") else "（可选）"
        parts.append(
            f'<p class="mt8"><span class="badge badge-mt">{html.escape(media_type)}</span>'
            f'<span class="badge badge-req">{required}</span></p>'
        )
        struct_type = html.escape(_schema_type(schema, components) or "—")
        parts.append(f'<p class="muted mt8">结构：<code>{struct_type}</code></p>')
        example = _example_for(schema, components)
        if example is not None:
            example_text = json.dumps(example, ensure_ascii=False, indent=2)
            parts.append(_render_code_block(f"请求示例（{media_type}）", example_text))
    return "".join(parts)


def _status_label(status: str) -> str:
    """把 HTTP 状态码映射为中文标签。

    Args:
        status: HTTP 状态码字符串。

    Returns:
        中文标签。
    """
    if status.startswith("2"):
        return "成功"
    mapping = {
        "400": "参数错误",
        "401": "未授权",
        "403": "越权",
        "404": "未找到",
        "422": "参数错误",
    }
    return mapping.get(status, "错误")


def _render_responses(operation: dict[str, Any], components: dict[str, Any]) -> str:
    """渲染响应说明与示例。

    多数业务接口的响应类型是泛型 `dict[str, Any]`（统一包络），
    自动生成的示例会是空对象。此处识别这种情形，补充统一包络结构示例，
    避免文档里出现「示例为空」的无信息量展示。

    Args:
        operation: OpenAPI 操作对象。
        components: OpenAPI components 字典。

    Returns:
        响应 HTML 片段。
    """
    responses = operation.get("responses") or {}
    if not responses:
        return ""
    parts: list[str] = ['<h4 class="sec-title">响应</h4>']
    for status in sorted(responses):
        resp = responses[status]
        schema = (resp.get("content") or {}).get("application/json", {}).get("schema") or {}
        label = _status_label(status)
        parts.append(
            f'<p class="mt8"><span class="badge badge-code">{html.escape(status)}</span>'
            f'<span class="badge badge-{label}">{label}</span>'
            f'<span class="muted ml8">{html.escape(resp.get("description", ""))}</span></p>'
        )
        if schema:
            example = _example_for(schema, components)
            if _is_generic_object(schema) and status.startswith("2"):
                example = {
                    "code": 0,
                    "data": {},
                    "message": "",
                }
                example_text = json.dumps(example, ensure_ascii=False, indent=2)
                parts.append(_render_code_block(f"响应示例（{status}）", example_text))
                parts.append(
                    '<p class="muted mt8">响应体为统一包络 <code>{code, data, message}</code>，'
                    "<code>code</code> 为 0 表示成功，非 0 为业务错误码。</p>"
                )
                continue
            if example is not None:
                example_text = json.dumps(example, ensure_ascii=False, indent=2)
                parts.append(_render_code_block(f"响应示例（{status}）", example_text))
    return "".join(parts)


def _is_generic_object(schema: dict[str, Any]) -> bool:
    """判断 schema 是否为泛型对象（无具体属性定义）。

    Args:
        schema: schema 字典。

    Returns:
        True 表示泛型对象。
    """
    if "$ref" in schema:
        return False
    return schema.get("type") == "object" and not schema.get("properties")


def _render_code_block(title: str, content: str) -> str:
    """渲染代码块。

    Args:
        title: 代码块标题。
        content: 代码文本。

    Returns:
        代码块 HTML 片段。
    """
    return (
        f'<div class="code-head">{html.escape(title)}</div>'
        f'<pre class="code">{html.escape(content)}</pre>'
    )


def _render_endpoint(endpoint: dict[str, Any], components: dict[str, Any]) -> str:
    """渲染单个接口的完整说明卡片。

    Args:
        endpoint: 接口条目。
        components: OpenAPI components 字典。

    Returns:
        接口卡片 HTML 片段。
    """
    operation = endpoint["operation"]
    anchor = _anchor_of(endpoint["method"], endpoint["path"])
    auth = "需鉴权" if operation.get("security") else "公开"
    auth_class = "badge-auth" if operation.get("security") else "badge-public"
    tag_attr = html.escape(endpoint["tag"])

    parts: list[str] = [
        f'<section class="ep" id="{html.escape(anchor)}" data-tag="{tag_attr}">',
        '<div class="ep-head">',
        f'<span class="m m-{endpoint["method"]}">{endpoint["method_label"]}</span>',
        f'<code class="path">{html.escape(endpoint["path"])}</code>',
        f'<span class="{auth_class}">{auth}</span>',
        "</div>",
    ]
    if endpoint["summary"]:
        parts.append(f'<h3 class="ep-title">{html.escape(endpoint["summary"])}</h3>')
    if endpoint["description"]:
        parts.append(f'<p class="ep-desc">{html.escape(endpoint["description"])}</p>')
    parts.append(_render_params(operation, components))
    parts.append(_render_request_body(operation, components))
    parts.append(_render_responses(operation, components))
    parts.append("</section>")
    return "".join(parts)


def _render_tag_info(schema: dict[str, Any]) -> str:
    """渲染标签分组说明。

    Args:
        schema: OpenAPI 规格字典。

    Returns:
        分组说明 HTML 片段。
    """
    tag_map = {t.get("name"): t.get("description", "") for t in schema.get("tags", [])}
    if not tag_map:
        return ""
    parts: list[str] = ['<div class="tag-cards">']
    for name, desc in tag_map.items():
        parts.append(
            f'<div class="tag-card"><div class="tag-name">{html.escape(name)}</div>'
            f'<div class="tag-desc">{html.escape(desc)}</div></div>'
        )
    parts.append("</div>")
    return "".join(parts)


def build_html(schema: dict[str, Any]) -> str:
    """构建完整的单文件 HTML 接口文档。

    Args:
        schema: OpenAPI 规格字典。

    Returns:
        HTML 文本。
    """
    components = schema.get("components", {})
    endpoints = _collect_endpoints(schema)

    # 按标签分组，生成左侧目录
    grouped: dict[str, list[dict[str, Any]]] = {}
    for endpoint in endpoints:
        grouped.setdefault(endpoint["tag"], []).append(endpoint)

    nav_parts: list[str] = []
    for tag, items in grouped.items():
        nav_parts.append(f'<div class="nav-group"><div class="nav-tag">{html.escape(tag)}</div>')
        for endpoint in items:
            anchor = _anchor_of(endpoint["method"], endpoint["path"])
            searchable = endpoint["path"] + " " + endpoint["summary"]
            nav_parts.append(
                f'<a class="nav-item" href="#{html.escape(anchor)}" '
                f'data-search="{html.escape(searchable)}">'
                f'<span class="m m-{endpoint["method"]}">{endpoint["method_label"]}</span>'
                f'<span class="nav-path">{html.escape(endpoint["path"])}</span></a>'
            )
        nav_parts.append("</div>")
    nav = "".join(nav_parts)

    body_parts: list[str] = []
    for tag, items in grouped.items():
        grp_id = html.escape(tag)
        body_parts.append(f'<h2 class="grp-title" id="grp-{grp_id}">{grp_id}</h2>')
        for endpoint in items:
            body_parts.append(_render_endpoint(endpoint, components))
    body = "".join(body_parts)

    info = schema.get("info", {})
    title = info.get("title", "API 接口文档")
    version = info.get("version", "")
    description = info.get("description", "")
    description_html = _render_markdown_lite(description)

    template = _load_template()
    placeholders = {
        "title": html.escape(title),
        "version": html.escape(str(version)),
        "endpoint_count": str(len(endpoints)),
        "group_count": str(len(grouped)),
        "auth_count": str(sum(1 for e in endpoints if e["operation"].get("security"))),
        "public_count": str(sum(1 for e in endpoints if not e["operation"].get("security"))),
        "description_html": description_html,
        "nav": nav,
        "tag_info": _render_tag_info(schema),
        "body": body,
    }
    for key, value in placeholders.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def _load_template() -> str:
    """读取 HTML 模板文件。

    Returns:
        模板文本（含 `{{placeholder}}` 占位符）。
    """
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _render_markdown_lite(text: str) -> str:
    """渲染极简 Markdown（标题/列表/代码块/行内代码/粗体）。

    Args:
        text: 原始 Markdown 文本。

    Returns:
        HTML 片段。
    """
    if not text:
        return ""
    out: list[str] = []
    in_code = False
    code_buf: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            if in_code:
                out.append(
                    "<pre><code>"
                    + html.escape("\n".join(code_buf))
                    + "</code></pre>"
                )
                code_buf = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_buf.append(raw)
            continue
        if not stripped:
            continue
        if stripped.startswith("### "):
            out.append(f"<h3>{_inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            out.append(f"<h3>{_inline(stripped[3:])}</h3>")
        elif stripped.startswith("- "):
            out.append(f"<li>{_inline(stripped[2:])}</li>")
        elif stripped.startswith("|"):
            out.append(f"<p>{_inline(stripped)}</p>")
        elif stripped.startswith("---"):
            out.append("<hr>")
        else:
            out.append(f"<p>{_inline(stripped)}</p>")
    return "".join(out)


def _inline(text: str) -> str:
    """渲染行内 Markdown（代码/粗体）。

    Args:
        text: 原始文本。

    Returns:
        HTML 片段。
    """
    escaped = html.escape(text)
    escaped = escaped.replace("`", "<code>").replace("</code><code>", "</code><code>")
    # 修正被替换产生的错位闭合标签
    parts = escaped.split("<code>")
    rebuilt = parts[0]
    for part in parts[1:]:
        rebuilt += "<code>" + part.replace("</code>", "</code>")
    return rebuilt


def main() -> None:
    """脚本入口：导出 HTML 接口文档。"""
    parser = argparse.ArgumentParser(description="导出可视化接口文档")
    parser.add_argument("--open", action="store_true", help="导出后用默认浏览器打开")
    parser.add_argument("--json", type=Path, default=None, help="同时导出 openapi.json 到指定路径")
    args = parser.parse_args()

    schema = app.openapi()
    output = build_html(schema)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print(f"[OK] 接口文档已生成: {OUTPUT_PATH}")

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] OpenAPI JSON 已生成: {args.json}")

    if args.open:
        webbrowser.open(OUTPUT_PATH.resolve().as_uri())


if __name__ == "__main__":
    main()
