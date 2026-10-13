"""Native Part Family operations; imported inside NX without third-party packages."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from nx_mcp.runtime import NXToolError


def _text(value: Any) -> str:
    if isinstance(value, str) and "\0" not in value:
        return value
    if type(value) is bool:
        return "1" if value else "0"
    if type(value) is int or (type(value) is float and math.isfinite(value)):
        return str(value)
    raise NXToolError("NX_INVALID_ARGUMENT", "Family values must be strings or finite scalars")


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise NXToolError("NX_INVALID_ARGUMENT", f"{field} must be a non-empty name")
    return value


class PartFamilyService:
    """Use TemplateManager without applying member values to the template geometry."""

    def __init__(self, executor: Any):
        self.executor = executor

    def _part(self, part_name: str | None) -> Any:
        if part_name is None:
            part = self.executor._work_part()
        else:
            _name(part_name, "part_name")
            matches = [
                p
                for p in self.executor.session.Parts
                if part_name.casefold()
                in {
                    str(p.Name).casefold(),
                    str(p.FullPath).casefold(),
                    Path(p.FullPath).name.casefold(),
                }
            ]
            if len(matches) != 1:
                raise NXToolError("NX_INVALID_ARGUMENT", "part_name must identify one open part")
            part = matches[0]
        self.executor.workspace.ensure_inside(part.FullPath)
        if self.executor._part_id(part) in self.executor._unsafe_parts:
            raise NXToolError("NX_ROLLBACK_FAILED", "The selected part requires recovery")
        return part

    @staticmethod
    def _family(part: Any) -> tuple[Any, Any, list[Any], list[str]]:
        manager = part.NewPartFamilyTemplateManager()
        template = manager.GetPartFamilyTemplate()
        if template is None:
            raise NXToolError("NX_NO_PART_FAMILY", "The selected part has no Part Family")
        attributes = list(manager.GetChosenAttributes())
        names = [a.Name for a in attributes]
        if len(set(names)) != len(names):
            raise NXToolError("NX_AMBIGUOUS_COLUMNS", "Family contains duplicate column names")
        return manager, template, attributes, list(template.GetMembers())

    @staticmethod
    def _row(manager: Any, attributes: list[Any], name: str, index: int) -> dict[str, Any]:
        definition = manager.GetInstanceDefinition(name)
        return {
            "row": index + 1,
            "member_name": name,
            "values": {a.Name: definition.GetValueOfAttribute(a) for a in attributes},
        }

    def get(
        self, part_name: str | None = None, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise NXToolError(
                "NX_INVALID_ARGUMENT", "offset >= 0 and limit between 1 and 200 required"
            )
        part = self._part(part_name)
        manager, template, attributes, members = self._family(part)
        return {
            "part_name": part.Name,
            "part_path": part.FullPath,
            "importable": bool(manager.Importable),
            "member_count": len(members),
            "columns": [{"name": a.Name, "type": str(a.Type)} for a in attributes],
            "members": [
                self._row(manager, attributes, name, index)
                for index, name in enumerate(members)
                if offset <= index < offset + limit
            ],
            "offset": offset,
            "next_offset": offset + limit if offset + limit < len(members) else None,
            "message": "Part Family read; values are NX strings, including expressions.",
        }

    def add(
        self,
        member_name: str,
        values: dict[str, Any],
        part_name: str | None = None,
        copy_from: str = "last",
        other_name: str | None = None,
        save: bool = False,
    ) -> dict[str, Any]:
        _name(member_name, "member_name")
        _name(copy_from, "copy_from")
        if type(save) is not bool or not isinstance(values, dict):
            raise NXToolError("NX_INVALID_ARGUMENT", "save must be boolean and values an object")
        part = self._part(part_name)
        manager, template, attributes, members = self._family(part)
        if not members:
            raise NXToolError("NX_EMPTY_PART_FAMILY", "No existing member is available to copy")
        if any(n.casefold() == member_name.casefold() for n in members):
            raise NXToolError("NX_DUPLICATE_MEMBER", "Member name already exists")
        #if not template.IsValidMemberName(member_name):
        #    raise NXToolError("NX_INVALID_ARGUMENT", "NX rejected the member name")
        source_name = members[-1] if copy_from == "last" else copy_from
        if source_name not in members:
            raise NXToolError(
                "NX_INVALID_ARGUMENT", "copy_from must be 'last' or an existing member name"
            )
        by_name = {a.Name: a for a in attributes}
        overrides: dict[str, str] = {}
        identity_names = {"OS_PART_NAME", "DB_PART_NO", "DB_PART_NAME"}
        for key, value in values.items():
            if key not in by_name:
                raise NXToolError("NX_UNKNOWN_COLUMN", f"Unknown Part Family column: {key}")
            if key in identity_names or str(by_name[key].Type).split(".")[-1] == "Name":
                raise NXToolError(
                    "NX_INVALID_ARGUMENT", "Use member_name/other_name for identity columns"
                )
            text = _text(value)
            kind = str(by_name[key].Type).split(".")[-1]
            if kind in {"Integer", "Numeric", "Double", "Density", "Mass"}:
                try:
                    number = float(text)
                    if not math.isfinite(number) or (kind == "Integer" and not number.is_integer()):
                        raise ValueError
                except (ValueError, OverflowError) as error:
                    raise NXToolError(
                        "NX_INVALID_ARGUMENT", f"Invalid {kind} value for {key}"
                    ) from error
            overrides[key] = text
        secondary = other_name if other_name is not None else member_name
        _name(secondary, "other_name")
        if manager.Importable:
            # Native mode: member_name is OS_PART_NAME; other_name is the DB identity.
            db_attrs = [a for a in attributes if a.Name in {"DB_PART_NO", "DB_PART_NAME"}]
            for name in members:
                existing = manager.GetInstanceDefinition(name)
                if any(
                    existing.GetValueOfAttribute(a).casefold() == secondary.casefold()
                    for a in db_attrs
                ):
                    raise NXToolError("NX_DUPLICATE_MEMBER", "other_name already exists")
        source = manager.GetInstanceDefinition(source_name)
        copied = {a.Name: source.GetValueOfAttribute(a) for a in attributes}
        session = self.executor.session
        mark = session.SetUndoMark(
            self.executor.nxopen.Session.MarkVisibility.Visible, "NX MCP: nx_add_part_family_member"
        )
        try:
            created = manager.AddInstanceDefinition(
                member_name, source, secondary if manager.Importable else ""
            )
            for attribute in attributes:
                if (
                    attribute.Name not in identity_names
                    and str(attribute.Type).split(".")[-1] != "Name"
                ):
                    created.SetValueOfAttribute(
                        attribute, overrides.get(attribute.Name, copied[attribute.Name])
                    )
            manager.SavePartFamily()
            current = list(template.GetMembers())
            if member_name not in current:
                raise NXToolError("NX_OPERATION_FAILED", "NX did not retain the new family member")
            row = self._row(manager, attributes, member_name, current.index(member_name))
            for key, value in overrides.items():
                if row["values"][key] != value:
                    raise NXToolError(
                        "NX_OPERATION_FAILED", f"NX did not retain the value for {key}"
                    )
        except Exception as error:
            self.executor._rollback(mark, error, self.executor._part_id(part))
            raise
        result = {
            "part_name": part.Name,
            "part_path": part.FullPath,
            "member": row,
            "copied_from": source_name,
            "saved": False,
            "generated": False,
            "message": "Added family table entry; no member .prt was generated.",
        }
        is_work_part = part is self.executor._work_part(required=False)
        if is_work_part:
            self.executor._undo_marks.append(mark)
        if save:
            # Saving is outside the undo transaction: a save failure must not claim the row vanished.
            status = None
            try:
                status = part.Save(
                    self.executor.nxopen.BasePart.SaveComponents.FalseValue,
                    self.executor.nxopen.BasePart.CloseAfterSave.FalseValue,
                )
                if status is not None and status.NumberUnsavedParts:
                    raise RuntimeError("NX reported unsaved parts")
                result["saved"] = True
            except Exception as error:
                raise NXToolError(
                    "NX_FAMILY_SAVE_FAILED",
                    "Member added in session but saving failed",
                    details={
                        "member": row,
                        "part_path": part.FullPath,
                        "save_error": str(error),
                        "saved": False,
                    },
                ) from error
            finally:
                if status is not None:
                    status.Dispose()
            if is_work_part:
                self.executor._undo_marks.clear()
        return result
