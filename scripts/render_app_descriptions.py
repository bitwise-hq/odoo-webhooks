from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

DESCRIPTION_ADDONS = (
    "bwt_webhooks_core",
    "bwt_webhooks_inbound",
    "bwt_webhooks_outbound",
    "bwt_connector_webhooks_core",
)

BANNER_ADDONS = (
    "bwt_webhooks_core",
    "bwt_webhooks_inbound",
    "bwt_webhooks_outbound",
    "bwt_connector_webhooks_core",
    "bwt_connector_webhooks_inbound",
    "bwt_connector_webhooks_outbound",
)

ADDON_NAMES = {
    "bwt_webhooks_core": "Webhooks Framework - Core Orchestration",
    "bwt_webhooks_inbound": "Webhooks Framework - Inbound Gateway",
    "bwt_webhooks_outbound": "Webhooks Framework - Outbound Delivery",
    "bwt_connector_webhooks_core": "Connector Webhooks - Glue Core",
    "bwt_connector_webhooks_inbound": "Connector Webhooks - Glue Inbound",
    "bwt_connector_webhooks_outbound": "Connector Webhooks - Glue Outbound",
}

ADDON_TAGLINES = {
    "bwt_webhooks_core": "Production-grade webhook orchestration for Odoo.",
    "bwt_webhooks_inbound": "Secure inbound endpoints with signatures, replay protection, and rule-based processing.",
    "bwt_webhooks_outbound": "Reliable outbound delivery with templated requests, retries, and diagnostics.",
    "bwt_connector_webhooks_core": "Shared base and mixins for connector backends that own webhook endpoints.",
    "bwt_connector_webhooks_inbound": "Mixin for connector backends to receive and process inbound webhooks.",
    "bwt_connector_webhooks_outbound": "Mixin for connector backends to send outbound webhooks reliably.",
}


def _find_bitwise_hq_root(repo_root: Path) -> Path:
    override = os.environ.get("BITWISE_HQ_ROOT")
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))

    for parent in (repo_root, *repo_root.parents):
        candidates.append(parent / "bitwise-hq")
        try:
            candidates.extend(child / "bitwise-hq" for child in parent.iterdir() if child.is_dir())
        except OSError:
            continue

    seen: set[Path] = set()
    shared_module_relpath = Path("scripts") / "odoo_addon_description_renderer.py"
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / shared_module_relpath).exists():
            return resolved

    raise FileNotFoundError(
        "Unable to find bitwise-hq/scripts/odoo_addon_description_renderer.py. "
        "Set BITWISE_HQ_ROOT to the local bitwise-hq repository root."
    )


def _load_shared_renderer(repo_root: Path):
    bitwise_hq_root = _find_bitwise_hq_root(repo_root)
    module_path = bitwise_hq_root / "scripts" / "odoo_addon_description_renderer.py"
    spec = importlib.util.spec_from_file_location("bitwise_hq_odoo_addon_description_renderer", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load shared renderer module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, bitwise_hq_root


REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_RENDERER, BITWISE_HQ_ROOT = _load_shared_renderer(REPO_ROOT)
RepositoryRenderConfig = SHARED_RENDERER.RepositoryRenderConfig
render_repository = SHARED_RENDERER.render_repository


def main() -> int:
    local_fonts_dir = REPO_ROOT / "assets" / "fonts"
    config = RepositoryRenderConfig(
        description_addons=DESCRIPTION_ADDONS,
        banner_addons=BANNER_ADDONS,
        addon_names=ADDON_NAMES,
        addon_taglines=ADDON_TAGLINES,
        fonts_dir=local_fonts_dir if local_fonts_dir.exists() else BITWISE_HQ_ROOT / "assets" / "fonts",
    )
    render_repository(REPO_ROOT, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
