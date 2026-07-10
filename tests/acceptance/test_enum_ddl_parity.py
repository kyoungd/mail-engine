"""Phase 0 gate: the Python enums and the DDL enum types cannot drift. This
parses `create type ... as enum (...)` out of migration 0001 and asserts each
label set exactly equals the corresponding StrEnum's values."""

import re
from pathlib import Path

import pytest

from domain.enums import DDL_ENUM_TYPES

MIGRATION_0001 = (
    Path(__file__).resolve().parent.parent.parent
    / "db"
    / "migrations"
    / "0001.create-schema.sql"
)

_ENUM_BLOCK = re.compile(
    r"create\s+type\s+(\w+)\s+as\s+enum\s*\((.*?)\)", re.IGNORECASE | re.DOTALL
)
_LABEL = re.compile(r"'([^']*)'")


def _ddl_enum_labels() -> dict[str, set[str]]:
    sql = MIGRATION_0001.read_text()
    return {
        name: set(_LABEL.findall(body)) for name, body in _ENUM_BLOCK.findall(sql)
    }


def test_ddl_and_code_declare_the_same_enum_types():
    assert set(_ddl_enum_labels()) == set(DDL_ENUM_TYPES)


@pytest.mark.parametrize("type_name", list(DDL_ENUM_TYPES))
def test_enum_labels_match_ddl(type_name):
    ddl_labels = _ddl_enum_labels()[type_name]
    code_labels = {member.value for member in DDL_ENUM_TYPES[type_name]}
    assert code_labels == ddl_labels
