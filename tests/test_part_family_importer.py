"""Tests for the external Part Family importer utility."""

from __future__ import annotations

import csv

import pytest

from nx_mcp.part_family_importer import (
    async_import_part_family,
    import_part_family_from_file,
    parse_data_file,
)
from nx_mcp.runtime import NXToolError

pytestmark = pytest.mark.fake_nx


class MockBridge:
    def __init__(self, columns=None, members=None, importable=True):
        self.part_name = "Bolt_Template.prt"
        self.part_path = "C:/parts/Bolt_Template.prt"
        self.importable = importable
        self.columns = columns or [
            {"name": "OS_PART_NAME", "type": "Name"},
            {"name": "DB_PART_NO", "type": "Name"},
            {"name": "SCREW_LENGTH", "type": "Expression"},
            {"name": "DIAMETER", "type": "Expression"},
            {"name": "THREAD_PITCH", "type": "Double"},
            {"name": "COUNT", "type": "Integer"},
        ]
        self.members = members or ["M10x30", "M10x40"]
        self.added_calls: list[dict] = []
        self.saved_parts: list[str] = []

    async def call(self, method: str, params: dict):
        if method == "nx_get_part_family":
            return {
                "part_name": self.part_name,
                "part_path": self.part_path,
                "importable": self.importable,
                "columns": self.columns,
                "members": [{"member_name": m, "values": {}} for m in self.members],
            }
        elif method == "nx_add_part_family_member":
            member_name = params["member_name"]
            if member_name in self.members:
                raise NXToolError("NX_DUPLICATE_MEMBER", f"Member {member_name} already exists")
            self.added_calls.append(params)
            self.members.append(member_name)
            return {"member": {"member_name": member_name}, "saved": params.get("save", False)}
        elif method == "nx_save_part":
            self.saved_parts.append(params.get("path", ""))
            return {"saved": True}
        raise NotImplementedError(f"Unexpected method: {method}")


@pytest.fixture
def mock_bridge():
    return MockBridge()


def test_parse_csv(tmp_path):
    csv_file = tmp_path / "test.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["member_name", "SCREW_LENGTH", "DIAMETER"])
        writer.writerow(["M10x50", "50", "10"])
        writer.writerow(["M10x60", "60", "10"])

    rows = parse_data_file(csv_file)
    assert len(rows) == 2
    assert rows[0]["member_name"] == "M10x50"
    assert rows[0]["SCREW_LENGTH"] == "50"
    assert rows[1]["member_name"] == "M10x60"


@pytest.mark.asyncio
async def test_async_import_success(mock_bridge):
    rows = [
        {"member_name": "M10x50", "SCREW_LENGTH": 50, "DIAMETER": 10},
        {"member_name": "M10x60", "SCREW_LENGTH": 60, "DIAMETER": 10},
    ]

    result = await async_import_part_family(
        rows=rows,
        save=True,
        client=mock_bridge,
    )

    assert result.is_success
    assert result.total_rows == 2
    assert result.added == ["M10x50", "M10x60"]
    assert len(mock_bridge.added_calls) == 2

    # Check that parameters passed do NOT contain identity column in values dict
    first_call = mock_bridge.added_calls[0]
    assert first_call["member_name"] == "M10x50"
    assert first_call["values"] == {"SCREW_LENGTH": 50, "DIAMETER": 10}
    assert "OS_PART_NAME" not in first_call["values"]

    # Check save was triggered on the last row
    assert mock_bridge.added_calls[-1]["save"] is True
    assert result.saved is True


@pytest.mark.asyncio
async def test_async_import_skips_existing(mock_bridge):
    rows = [
        {"member_name": "M10x30", "SCREW_LENGTH": 30},  # already exists in mock_bridge
        {"member_name": "M10x70", "SCREW_LENGTH": 70},
    ]

    result = await async_import_part_family(
        rows=rows,
        skip_existing=True,
        client=mock_bridge,
    )

    assert result.is_success
    assert len(result.added) == 1
    assert result.added == ["M10x70"]
    assert len(result.skipped) == 1
    assert result.skipped[0][0] == "M10x30"


@pytest.mark.asyncio
async def test_async_import_ignores_unknown_columns(mock_bridge):
    rows = [
        {
            "member_name": "M10x80",
            "SCREW_LENGTH": 80,
            "NOTES_FOR_MANUFACTURING": "Ignore this metadata",
            "EXTRA_FIELD": 12345,
        }
    ]

    result = await async_import_part_family(
        rows=rows,
        client=mock_bridge,
    )

    assert result.is_success
    assert len(result.added) == 1
    call_values = mock_bridge.added_calls[0]["values"]
    assert "SCREW_LENGTH" in call_values
    assert "NOTES_FOR_MANUFACTURING" not in call_values
    assert "EXTRA_FIELD" not in call_values


@pytest.mark.asyncio
async def test_async_import_dry_run(mock_bridge):
    rows = [
        {"member_name": "M10x90", "SCREW_LENGTH": 90},
    ]

    result = await async_import_part_family(
        rows=rows,
        dry_run=True,
        client=mock_bridge,
    )

    assert result.is_success
    assert result.added == ["M10x90"]
    # In dry run, no calls to add should have been made to the bridge
    assert len(mock_bridge.added_calls) == 0


def test_import_from_file_sync(mock_bridge, tmp_path):
    csv_file = tmp_path / "screws.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["part_name", "SCREW_LENGTH", "DIAMETER"])
        writer.writerow(["M10x100", "100", "10"])

    result = import_part_family_from_file(
        csv_file,
        client=mock_bridge,
    )

    assert result.is_success
    assert result.added == ["M10x100"]
    assert len(mock_bridge.added_calls) == 1
