"""Platform-neutral engineering-assistant kernel."""

from .runtime.catalog import Catalog, load_catalog
from .runtime.version import CANONICAL_VERSION, STABLE_VERSION

__all__ = ["CANONICAL_VERSION", "STABLE_VERSION", "Catalog", "load_catalog"]
