#!/usr/bin/env python3
import json
from pathlib import Path

MANIFEST = Path("engineering-assistant/plugin/plugin.json")
manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

errors = []
warnings = []

required_top_level = ["name", "version", "description", "author", "homepage", "repository", "license", "skills", "interface", "metadata_status", "distribution_notes"]
for field in required_top_level:
    if field not in manifest:
        errors.append(f"{MANIFEST}: 缺少 {field}")

interface = manifest.get("interface", {})
for field in ["displayName", "shortDescription", "longDescription", "developerName", "category", "capabilities", "defaultPrompt", "brandColor", "websiteURL", "privacyPolicyURL", "termsOfServiceURL"]:
    if field not in interface:
        errors.append(f"{MANIFEST}: interface 缺少 {field}")

notes = manifest.get("distribution_notes", {})
if manifest.get("metadata_status") not in {"ready", "waiting_for_human_review"}:
    errors.append(f"{MANIFEST}: metadata_status 必须为 ready 或 waiting_for_human_review")
if notes.get("runtime_policy_pack") != "target-project-template":
    errors.append(f"{MANIFEST}: distribution_notes.runtime_policy_pack 必须声明为 target-project-template")
if notes.get("hooks_packaging") != "not-bundled":
    errors.append(f"{MANIFEST}: distribution_notes.hooks_packaging 必须声明为 not-bundled")

placeholder_values = []
author = manifest.get("author", {})
for path, value in [
    ("author.email", author.get("email", "")),
    ("author.url", author.get("url", "")),
    ("homepage", manifest.get("homepage", "")),
    ("repository", manifest.get("repository", "")),
    ("interface.websiteURL", interface.get("websiteURL", "")),
    ("interface.privacyPolicyURL", interface.get("privacyPolicyURL", "")),
    ("interface.termsOfServiceURL", interface.get("termsOfServiceURL", "")),
]:
    if "example." in str(value) or str(value).endswith("@example.com"):
        placeholder_values.append(path)

if placeholder_values:
    if manifest.get("metadata_status") != "waiting_for_human_review":
        errors.append(f"{MANIFEST}: 占位符 metadata {placeholder_values} 只能在 waiting_for_human_review 状态下保留")
    if notes.get("external_distribution_gate") != "waiting_for_human_review":
        errors.append(f"{MANIFEST}: 占位符 metadata 必须声明 external_distribution_gate=waiting_for_human_review")
    if notes.get("placeholder_metadata_allowed_for_local_template") is not True:
        errors.append(f"{MANIFEST}: 占位符 metadata 必须显式声明仅允许 local template")
    warnings.append("example.* placeholder metadata requires human review: " + ", ".join(placeholder_values))

if "hooks" in manifest:
    errors.append(f"{MANIFEST}: runtime policy pack 当前是目标项目模板，不得在 manifest 中声明 hooks")

runtime_readme = Path("engineering-assistant/runtime/codex/README.md")
if runtime_readme.exists():
    readme_text = runtime_readme.read_text(encoding="utf-8")
    for required_text in ["安装插件不等于自动启用", "不作为插件内置 hooks 自动生效", "trust review"]:
        if required_text not in readme_text:
            errors.append(f"{runtime_readme}: 缺少 runtime 模板定位说明 {required_text}")
else:
    errors.append(f"{runtime_readme}: 缺少 runtime policy pack README")

for profile in ["readonly_review.toml", "controlled_fix.toml"]:
    path = Path("engineering-assistant/runtime/codex/profiles") / profile
    if not path.exists():
        errors.append(f"{path}: 缺少独立 profile 示例")

status = "block" if errors else ("waiting_for_human_review" if warnings else "pass")
payload = {"status": status, "errors": errors, "warnings": warnings}
if errors:
    raise SystemExit(json.dumps(payload, ensure_ascii=False, indent=2))
print(json.dumps(payload, ensure_ascii=False, indent=2))
