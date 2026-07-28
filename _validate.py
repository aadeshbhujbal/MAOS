import importlib
import sys
import tomllib
from pathlib import Path

root = Path(__file__).parent
data = tomllib.load(open(root / "pyproject.toml", "rb"))
print("pyproject OK ->", data["project"]["name"], data["project"]["requires-python"])

sys.path.insert(0, str(root / "src"))
pkgs = [
    "maos",
    "maos.core",
    "maos.contracts",
    "maos.registry",
    "maos.memory",
    "maos.messaging",
    "maos.llm",
    "maos.mcp",
    "maos.audit",
    "maos.cost",
    "maos.security",
    "maos.graphs",
    "maos.api",
    "maos.observability",
    "maos.config",
]
for name in pkgs:
    importlib.import_module(name)
    print("import OK ->", name)
print("ALL IMPORTS OK, version =", importlib.import_module("maos").__version__)
