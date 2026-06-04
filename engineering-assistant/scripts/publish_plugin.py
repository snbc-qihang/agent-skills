#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path

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
    raise SystemExit(f"unsupported publish layout: {layout}")


def publish(repo_root: Path, config: dict, publish_root=None, marketplace_path=None, layout="local-root") -> dict:
    config = apply_layout(config, layout)
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


def main():
    parser = argparse.ArgumentParser(description="Publish teamwork-engineering-assistant as a Codex-recognizable local plugin.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--layout", choices=["local-root", "personal"], default="local-root", help="local-root uses configured publish_root; personal writes the canonical Codex personal marketplace under ~/.agents/plugins.")
    parser.add_argument("--publish-root")
    parser.add_argument("--marketplace-path")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    config = load_config(repo_root / args.config if not Path(args.config).is_absolute() else Path(args.config))
    publish_root = expand(args.publish_root) if args.publish_root else None
    marketplace_path = expand(args.marketplace_path) if args.marketplace_path else None
    print(json.dumps(publish(repo_root, config, publish_root, marketplace_path, args.layout), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
