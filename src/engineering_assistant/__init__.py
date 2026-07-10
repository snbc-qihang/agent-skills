"""Platform-neutral engineering-assistant kernel."""

from .catalog import Catalog, load_catalog
from .version import CANONICAL_VERSION, STABLE_VERSION

__all__ = ["CANONICAL_VERSION", "STABLE_VERSION", "Catalog", "load_catalog"]
