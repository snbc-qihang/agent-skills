#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover - Hermes installs include PyYAML; creation-only mode can still work without it.
    yaml = None

DEFAULT_CONFIG = Path(".agent/plugins/publish-config.json")


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"missing publish config: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def expand(path_value: str) -> Path:
    return Path(path_value).expanduser().resolve()


def ensure_not_repo_path(repo_root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return
    raise SystemExit(f"refuse to publish into repository workspace: {path}")


def copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        raise SystemExit(f"missing source tree: {source}")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def read_codex_manifest(repo_root: Path) -> dict:
    manifest = repo_root / "engineering-assistant" / "plugin" / "plugin.json"
    if not manifest.exists():
        raise SystemExit(f"missing plugin manifest source: {manifest}")
    return json.loads(manifest.read_text(encoding="utf-8"))


def plugin_entry(config: dict) -> dict:
    plugin_name = config.get("plugin_name", "teamwork-engineering-assistant")
    return {
        "name": plugin_name,
        "source": {
            "source": "local",
            "path": "./" + config.get("plugin_relative_path", f"plugins/{plugin_name}").strip("/"),
        },
        "policy": config.get("policy", {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}),
        "category": config.get("category", "Productivity"),
    }


def load_marketplace(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid marketplace json: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"marketplace must be a JSON object: {path}")
    return data


def upsert_plugin_entry(existing_plugins, entry: dict) -> list:
    plugins = existing_plugins if isinstance(existing_plugins, list) else []
    updated = []
    replaced = False
    for item in plugins:
        if isinstance(item, dict) and item.get("name") == entry["name"]:
            updated.append(entry)
            replaced = True
        else:
            updated.append(item)
    if not replaced:
        updated.append(entry)
    return updated


def marketplace_payload(config: dict, existing=None) -> dict:
    payload = dict(existing or {})
    return {
        **payload,
        "name": payload.get("name") or config.get("name", "local-teamwork-engineering"),
        "interface": payload.get("interface") if isinstance(payload.get("interface"), dict) else config.get("interface", {"displayName": "Local Teamwork Engineering Plugins"}),
        "plugins": upsert_plugin_entry(payload.get("plugins"), plugin_entry(config)),
    }


def apply_layout(config: dict, layout: str) -> dict:
    resolved = dict(config)
    if layout == "local-root":
        return resolved
    if layout == "personal":
        resolved["name"] = "personal"
        resolved["interface"] = {"displayName": "Personal"}
        resolved["publish_root"] = "~"
        resolved["marketplace_path"] = "~/.agents/plugins/marketplace.json"
        resolved["plugin_relative_path"] = f"plugins/{resolved.get('plugin_name', 'teamwork-engineering-assistant')}"
        return resolved
    if layout == "hermes":
        resolved["publish_root"] = resolved.get("hermes_publish_root", "~/.hermes")
        resolved["plugin_relative_path"] = f"plugins/{resolved.get('plugin_name', 'teamwork-engineering-assistant')}"
        return resolved
    raise SystemExit(f"unsupported publish layout: {layout}")


def hermes_plugin_yaml(plugin_name: str, manifest: dict) -> str:
    author = manifest.get("author", {})
    author_name = author.get("name", "") if isinstance(author, dict) else str(author)
    payload = {
        "name": plugin_name,
        "version": str(manifest.get("version", "1.0.0")),
        "description": manifest.get("description", ""),
        "author": author_name,
        "kind": "standalone",
        "platforms": ["linux", "macos", "windows"],
    }
    if yaml is not None:
        return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def hermes_entrypoint() -> str:
    return '''# Hermes adapter for the teamwork-engineering-assistant skill bundle.

from __future__ import annotations

from pathlib import Path


def _skill_description(skill_md: Path) -> str:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except Exception:
        return ""
    if not text.startswith("---"):
        return ""
    end = text.find("\\n---", 3)
    if end == -1:
        return ""
    for line in text[3:end].splitlines():
        if line.startswith("description:"):
            value = line.partition(":")[2].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
    return ""


def register(ctx) -> None:
    root = Path(__file__).resolve().parent
    skills_root = root / "skills"
    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        skill_name = skill_md.parent.name
        ctx.register_skill(
            skill_name,
            skill_md,
            description=_skill_description(skill_md),
        )
'''


def enable_hermes_plugin(hermes_home: Path, plugin_name: str) -> bool:
    config_path = hermes_home / "config.yaml"
    if not config_path.exists():
        config_path.write_text(
            "plugins:\n  enabled:\n    - " + plugin_name + "\n",
            encoding="utf-8",
        )
        return True
    if yaml is None:
        if plugin_name in config_path.read_text(encoding="utf-8"):
            return True
        raise SystemExit("PyYAML is required to update an existing Hermes config.yaml")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(config, dict):
        raise SystemExit(f"unsupported Hermes config shape: {config_path}")
    plugins = config.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        raise SystemExit(f"unsupported Hermes plugins config shape: {config_path}")
    enabled = plugins.setdefault("enabled", [])
    if enabled is None:
        enabled = []
        plugins["enabled"] = enabled
    if not isinstance(enabled, list):
        raise SystemExit(f"unsupported Hermes plugins.enabled config shape: {config_path}")
    if plugin_name not in enabled:
        enabled.append(plugin_name)
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return True


def publish_hermes(repo_root: Path, config: dict, publish_root=None, enable=False) -> dict:
    plugin_name = config.get("plugin_name", "teamwork-engineering-assistant")
    publish_root = publish_root or expand(config["publish_root"])
    plugin_relative = Path(config.get("plugin_relative_path", f"plugins/{plugin_name}"))
    plugin_root = publish_root / plugin_relative
    ensure_not_repo_path(repo_root, publish_root)

    skills = repo_root / "skills"
    runtime = repo_root / "engineering-assistant"
    manifest = read_codex_manifest(repo_root)

    plugin_root.parent.mkdir(parents=True, exist_ok=True)
    if plugin_root.exists():
        shutil.rmtree(plugin_root)
    plugin_root.mkdir(parents=True)
    copy_tree(skills, plugin_root / "skills")
    copy_tree(runtime, plugin_root / "engineering-assistant")
    (plugin_root / "plugin.yaml").write_text(hermes_plugin_yaml(plugin_name, manifest), encoding="utf-8")
    (plugin_root / "__init__.py").write_text(hermes_entrypoint(), encoding="utf-8")

    hermes_enabled = enable_hermes_plugin(publish_root, plugin_name) if enable else False
    return {
        "status": "published",
        "layout": "hermes",
        "plugin_root": str(plugin_root),
        "hermes_plugin_manifest": str(plugin_root / "plugin.yaml"),
        "hermes_plugin_entrypoint": str(plugin_root / "__init__.py"),
        "hermes_enabled": hermes_enabled,
        "registered_skill_count": len(list((plugin_root / "skills").glob("*/SKILL.md"))),
    }


def publish_codex(repo_root: Path, config: dict, publish_root=None, marketplace_path=None, layout="local-root") -> dict:
    plugin_name = config.get("plugin_name", "teamwork-engineering-assistant")
    compatibility_alias = config.get("compatibility_alias")
    publish_root_override = publish_root is not None
    publish_root = publish_root or expand(config["publish_root"])
    if marketplace_path is None:
        marketplace_path = publish_root / ".agents" / "plugins" / "marketplace.json" if publish_root_override else expand(config.get("marketplace_path", str(publish_root / ".agents" / "plugins" / "marketplace.json")))
    plugin_relative = Path(config.get("plugin_relative_path", f"plugins/{plugin_name}"))
    plugin_root = publish_root / plugin_relative
    ensure_not_repo_path(repo_root, publish_root)
    ensure_not_repo_path(repo_root, marketplace_path)

    manifest = repo_root / "engineering-assistant" / "plugin" / "plugin.json"
    skills = repo_root / "skills"
    runtime = repo_root / "engineering-assistant"
    if not manifest.exists():
        raise SystemExit(f"missing plugin manifest source: {manifest}")

    plugin_root.parent.mkdir(parents=True, exist_ok=True)
    if plugin_root.exists():
        shutil.rmtree(plugin_root)
    (plugin_root / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest, plugin_root / ".codex-plugin" / "plugin.json")
    copy_tree(skills, plugin_root / "skills")
    copy_tree(runtime, plugin_root / "engineering-assistant")

    existing_marketplace = load_marketplace(marketplace_path)
    existing_plugin_names = {item.get("name") for item in existing_marketplace.get("plugins", []) if isinstance(item, dict)}
    if layout == "personal" and compatibility_alias and compatibility_alias != plugin_name and compatibility_alias not in existing_plugin_names:
        alias_root = publish_root / "plugins" / compatibility_alias
        if alias_root != plugin_root:
            if alias_root.exists():
                shutil.rmtree(alias_root)
            shutil.copytree(plugin_root, alias_root)

    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    marketplace_path.write_text(json.dumps(marketplace_payload(config, existing_marketplace), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    legacy_marketplace = publish_root / "marketplace.json"
    if legacy_marketplace != marketplace_path and legacy_marketplace.exists():
        legacy_marketplace.unlink()
    return {
        "status": "published",
        "layout": layout,
        "plugin_root": str(plugin_root),
        "marketplace_path": str(marketplace_path),
        "plugin_manifest": str(plugin_root / ".codex-plugin" / "plugin.json"),
    }


def publish(repo_root: Path, config: dict, publish_root=None, marketplace_path=None, layout="local-root", enable=False) -> dict:
    config = apply_layout(config, layout)
    if layout == "hermes":
        return publish_hermes(repo_root, config, publish_root=publish_root, enable=enable)
    if enable:
        raise SystemExit("--enable is only supported with --layout hermes")
    return publish_codex(repo_root, config, publish_root=publish_root, marketplace_path=marketplace_path, layout=layout)


def main():
    parser = argparse.ArgumentParser(description="Publish teamwork-engineering-assistant as a Codex or Hermes local plugin.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--layout", choices=["local-root", "personal", "hermes"], default="local-root", help="local-root uses configured Codex publish_root; personal writes the canonical Codex personal marketplace; hermes writes a Hermes directory plugin.")
    parser.add_argument("--publish-root")
    parser.add_argument("--marketplace-path")
    parser.add_argument("--enable", action="store_true", help="For --layout hermes, add the plugin to <publish-root>/config.yaml plugins.enabled.")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    config = load_config(repo_root / args.config if not Path(args.config).is_absolute() else Path(args.config))
    publish_root = expand(args.publish_root) if args.publish_root else None
    marketplace_path = expand(args.marketplace_path) if args.marketplace_path else None
    print(json.dumps(publish(repo_root, config, publish_root, marketplace_path, args.layout, args.enable), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
