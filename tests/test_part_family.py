"""Part Family contract/transaction tests. These do not certify live NX execution."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from mcp.client import Client

from nx_mcp.part_family import PartFamilyService
from nx_mcp.runtime import NXToolError
from nx_mcp.server import create_server
from nx_mcp.workspace import Workspace

pytestmark = pytest.mark.fake_nx


class Definition:
    def __init__(self, values):
        self.values = values

    def GetValueOfAttribute(self, attribute):
        return self.values[attribute.Name]

    def SetValueOfAttribute(self, attribute, value):
        if value == "NX_FAIL":
            raise RuntimeError("NX rejected expression")
        self.values[attribute.Name] = value


class Manager:
    Importable = True

    def __init__(self):
        self.attributes = [
            SimpleNamespace(Name=name, Type=kind)
            for name, kind in [
                ("OS_PART_NAME", "Name"),
                ("DB_PART_NO", "Name"),
                ("SCREW_LENGTH", "Expression"),
                ("COUNT", "Integer"),
                ("DESCRIPTION", "String"),
            ]
        ]
        self.rows = {
            "M24x55": Definition(
                {
                    "OS_PART_NAME": "M24x55",
                    "DB_PART_NO": "DIN55",
                    "SCREW_LENGTH": "55",
                    "COUNT": "1",
                    "DESCRIPTION": "cup point",
                }
            ),
            "M24x60": Definition(
                {
                    "OS_PART_NAME": "M24x60",
                    "DB_PART_NO": "DIN60",
                    "SCREW_LENGTH": "60",
                    "COUNT": "2",
                    "DESCRIPTION": "last row",
                }
            ),
        }
        self.saved_family = False

    def GetPartFamilyTemplate(self):
        return self

    def GetChosenAttributes(self):
        return self.attributes

    def GetMembers(self):
        return list(self.rows)

    def IsValidMemberName(self, name):
        return "/" not in name

    def GetInstanceDefinition(self, name):
        return self.rows[name]

    def AddInstanceDefinition(self, name, previous, other):
        self.rows[name] = Definition({"OS_PART_NAME": name, "DB_PART_NO": other})
        return self.rows[name]

    def SavePartFamily(self):
        self.saved_family = True


@pytest.fixture
def service(tmp_path):
    manager = Manager()
    part = SimpleNamespace(
        Name="Screw",
        FullPath=str(tmp_path / "Screw.prt"),
        NewPartFamilyTemplateManager=lambda: manager,
    )
    part.Save = lambda *args: None
    parts = type("Parts", (), {"Work": part, "__iter__": lambda self: iter([part])})()
    snapshot = {}

    def mark(*args):
        snapshot["rows"] = deepcopy(manager.rows)
        return 1

    def rollback(*args):
        manager.rows = snapshot["rows"]

    executor = SimpleNamespace(
        session=SimpleNamespace(Parts=parts, SetUndoMark=mark),
        workspace=Workspace(tmp_path),
        _work_part=lambda **kwargs: part,
        _part_id=lambda p: "part1",
        _unsafe_parts=set(),
        _undo_marks=[],
        _rollback=rollback,
        nxopen=SimpleNamespace(
            Session=SimpleNamespace(MarkVisibility=SimpleNamespace(Visible=True)),
            BasePart=SimpleNamespace(
                SaveComponents=SimpleNamespace(FalseValue=False),
                CloseAfterSave=SimpleNamespace(FalseValue=False),
            ),
        ),
    )
    return PartFamilyService(executor), manager, part


def test_query_pagination_and_explicit_part(service):
    tool, _, _ = service
    result = tool.get("Screw.prt", offset=1, limit=1)
    assert result["member_count"] == 2
    assert result["members"][0]["member_name"] == "M24x60"
    assert result["members"][0]["row"] == 2
    assert result["next_offset"] is None
    assert tool.get(limit=1)["next_offset"] == 1


def test_clone_preserves_values_and_generates_unique_identity(service):
    tool, manager, _ = service
    result = tool.add("M24x100", {"SCREW_LENGTH": 100}, other_name="DIN100")
    assert result["member"]["values"] == {
        "OS_PART_NAME": "M24x100",
        "DB_PART_NO": "DIN100",
        "SCREW_LENGTH": "100",
        "COUNT": "2",
        "DESCRIPTION": "last row",
    }
    assert manager.rows["M24x60"].values["SCREW_LENGTH"] == "60"
    assert result["saved"] is False and result["generated"] is False
    assert manager.saved_family


def test_select_source_and_save_selected_part(service):
    tool, _, part = service
    calls = []
    part.Save = lambda *args: calls.append(args)
    result = tool.add("long", {"SCREW_LENGTH": "60 + 40"}, copy_from="M24x55", save=True)
    assert result["member"]["values"]["COUNT"] == "1"
    assert result["saved"] is True
    assert calls == [(False, False)]


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"NO_SUCH_COLUMN": 100}, "NX_UNKNOWN_COLUMN"),
        ({"COUNT": 2.5}, "NX_INVALID_ARGUMENT"),
        ({"COUNT": "NaN"}, "NX_INVALID_ARGUMENT"),
        ({"SCREW_LENGTH": None}, "NX_INVALID_ARGUMENT"),
        ({"SCREW_LENGTH": float("inf")}, "NX_INVALID_ARGUMENT"),
        ({"SCREW_LENGTH": {"nested": 1}}, "NX_INVALID_ARGUMENT"),
        ({"OS_PART_NAME": "another"}, "NX_INVALID_ARGUMENT"),
    ],
)
def test_invalid_values_fail_before_mutation(service, changes, code):
    tool, manager, _ = service
    with pytest.raises(NXToolError) as error:
        tool.add("new", changes)
    assert error.value.code == code
    assert len(manager.rows) == 2


@pytest.mark.parametrize("name,other", [("M24x60", None), ("new", "DIN60")])
def test_duplicate_identities_rejected(service, name, other):
    tool, _, _ = service
    with pytest.raises(NXToolError, match="already exists"):
        tool.add(name, {}, other_name=other)


def test_api_failure_rolls_back_row(service):
    tool, manager, _ = service
    with pytest.raises(RuntimeError, match="rejected"):
        tool.add("new", {"SCREW_LENGTH": "NX_FAIL"})
    assert list(manager.rows) == ["M24x55", "M24x60"]


def test_save_failure_reports_retained_row(service):
    tool, manager, part = service

    def fail(*args):
        raise RuntimeError("disk unavailable")

    part.Save = fail
    with pytest.raises(NXToolError) as error:
        tool.add("new", {"SCREW_LENGTH": 100}, save=True)
    assert error.value.code == "NX_FAMILY_SAVE_FAILED"
    assert error.value.details["member"]["member_name"] == "new"
    assert "new" in manager.rows
    assert tool.executor._undo_marks


def test_query_rejects_non_workspace_part(service, tmp_path):
    tool, _, part = service
    part.FullPath = str(tmp_path.parent / "outside.prt")
    with pytest.raises(ValueError):
        tool.get()


@pytest.mark.asyncio
async def test_mcp_opt_in_and_dynamic_dictionary():
    class Bridge:
        calls = []

        async def call(self, method, params):
            self.calls.append((method, params))
            return {"saved": False, "generated": False}

    bridge = Bridge()
    async with Client(create_server(bridge)) as client:
        assert "nx_get_part_family" not in {t.name for t in (await client.list_tools()).tools}
    async with Client(create_server(bridge, enable_experimental=True)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert "nx_get_part_family" in tools and "nx_add_part_family_member" in tools
        result = await client.call_tool(
            "nx_add_part_family_member",
            {
                "member_name": "new",
                "values": {"SCREW_LENGTH": 100, "DESCRIPTION": "example"},
            },
        )
        assert not result.is_error
        invalid = await client.call_tool(
            "nx_add_part_family_member",
            {
                "member_name": "bad",
                "values": {"SCREW_LENGTH": {"nested": 100}},
            },
        )
        assert invalid.is_error
    assert len(bridge.calls) == 1
    assert bridge.calls[0][1]["values"]["SCREW_LENGTH"] == 100
