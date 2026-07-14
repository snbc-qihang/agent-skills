#!/usr/bin/env python3
import argparse
import html
import json
import re
from pathlib import Path

SECRET = re.compile(r"(?i)(token|password|passwd|secret|key|credential|authorization)(\s*[=:]\s*)([^\s<>&]+)")


def load_json(path: Path):
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def redact(value):
    text = "" if value is None else str(value)
    return SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)


def esc(value):
    return html.escape(redact(value))


def findings_from(*payloads):
    items = []
    for payload in payloads:
        if isinstance(payload, dict):
            for key in ["findings", "issues", "comments"]:
                if isinstance(payload.get(key), list):
                    items.extend(payload[key])
    return items


def pick(item, *keys, default=""):
    for key in keys:
        if isinstance(item, dict) and item.get(key) not in (None, ""):
            return item.get(key)
    return default


def count_by(findings, *keys):
    result = {}
    for item in findings:
        value = str(pick(item, *keys, default="unknown")).lower()
        result[value] = result.get(value, 0) + 1
    return result


def render_badges(counts):
    if not counts:
        return '<span class="muted">无数据</span>'
    return "".join(f'<span class="badge">{esc(k)} <strong>{v}</strong></span>' for k, v in sorted(counts.items()))


def render_table(findings):
    rows = []
    for index, item in enumerate(findings, start=1):
        fid = pick(item, "id", "rule", "rule_id", default=f"finding-{index}")
        severity = pick(item, "severity", "level", "priority", default="unknown")
        dimension = pick(item, "dimension", "category", "type", default="unknown")
        file_name = pick(item, "file", "path", "location", default="")
        line = pick(item, "line", "start_line", "start", default="")
        title = pick(item, "title", "message", "problem", "summary", default="")
        impact = pick(item, "impact", "risk", default="")
        suggestion = pick(item, "suggestion", "recommendation", "fix", default="")
        rows.append(f"<tr><td>{esc(fid)}</td><td>{esc(severity)}</td><td>{esc(dimension)}</td><td>{esc(file_name)}:{esc(line)}</td><td>{esc(title)}</td><td>{esc(impact)}</td><td>{esc(suggestion)}</td></tr>")
    return "\n".join(rows) or '<tr><td colspan="7" class="muted">未登记 finding</td></tr>'


def main():
    parser = argparse.ArgumentParser(description="Render a rich HTML report for manual code review.")
    parser.add_argument("--review-json", default="")
    parser.add_argument("--quality-json", default="")
    parser.add_argument("--static-json", default="")
    parser.add_argument("--markdown", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--title", default="代码走查报告")
    args = parser.parse_args()

    review = load_json(Path(args.review_json)) if args.review_json else {}
    quality = load_json(Path(args.quality_json)) if args.quality_json else {}
    static = load_json(Path(args.static_json)) if args.static_json else {}
    markdown = Path(args.markdown).read_text(encoding="utf-8") if args.markdown and Path(args.markdown).exists() else ""
    findings = findings_from(review, quality, static)
    gate = quality.get("gate_decision") or review.get("gate_decision") or review.get("status") or "unknown"
    tool_rows = []
    for tool in static.get("tools", []):
        tool_rows.append(f"<tr><td>{esc(tool.get('name'))}</td><td>{esc(tool.get('status'))}</td><td>{esc(tool.get('reason', ''))}</td></tr>")
    html_text = f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(args.title)}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1f2933; background: #f6f8fb; }}
    header {{ background: #0f172a; color: white; padding: 24px 32px; }}
    main {{ padding: 24px 32px; }}
    section {{ background: white; border: 1px solid #d9e2ec; border-radius: 8px; padding: 18px; margin: 0 0 18px; }}
    h1, h2 {{ margin: 0 0 12px; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .metric {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; }}
    .metric strong {{ display: block; font-size: 22px; margin-top: 6px; }}
    .badge {{ display: inline-block; margin: 4px 6px 4px 0; padding: 5px 8px; border-radius: 999px; background: #e8f1ff; color: #163b73; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #e5eaf0; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; }}
    pre {{ white-space: pre-wrap; background: #0b1020; color: #dbeafe; padding: 12px; border-radius: 6px; max-height: 360px; overflow: auto; }}
    .muted {{ color: #697586; }}
  </style>
</head>
<body>
  <header><h1>{esc(args.title)}</h1><div>gate decision: <strong>{esc(gate)}</strong></div></header>
  <main>
    <section class="summary">
      <div class="metric">Findings<strong>{len(findings)}</strong></div>
      <div class="metric">Severity<div>{render_badges(count_by(findings, "severity", "level", "priority"))}</div></div>
      <div class="metric">Quality Dimension<div>{render_badges(count_by(findings, "dimension", "category", "type"))}</div></div>
    </section>
    <section>
      <h2>静态分析工具状态</h2>
      <table><thead><tr><th>工具</th><th>状态</th><th>原因/说明</th></tr></thead><tbody>{''.join(tool_rows) or '<tr><td colspan="3" class="muted">未提供工具执行报告</td></tr>'}</tbody></table>
    </section>
    <section>
      <h2>问题清单</h2>
      <table><thead><tr><th>ID</th><th>级别</th><th>维度</th><th>位置</th><th>问题</th><th>影响</th><th>建议</th></tr></thead><tbody>{render_table(findings)}</tbody></table>
    </section>
    <section>
      <h2>人工确认区</h2>
      <label><input type="checkbox"> blocker 已逐项确认</label><br>
      <label><input type="checkbox"> 静态分析缺失项已有审批或修复计划</label><br>
      <label><input type="checkbox"> 高风险问题已有 owner 和完成时间</label>
    </section>
    <section>
      <h2>Markdown 摘要</h2>
      <pre>{esc(markdown[-20000:])}</pre>
    </section>
  </main>
</body>
</html>
'''
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(html_text, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
