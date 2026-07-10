"""Rule discovery: one rule per file, each exposing a module-level `RULE`. Adding a
rule is adding a file — there is no registry to update."""

import importlib
import pkgutil

from judgment.protocol import Rule


def all_rules() -> list[Rule]:
    rules: list[Rule] = []
    for module in pkgutil.iter_modules(__path__):
        loaded = importlib.import_module(f"{__name__}.{module.name}")
        rule = getattr(loaded, "RULE", None)
        if rule is not None:
            rules.append(rule)
    return rules
