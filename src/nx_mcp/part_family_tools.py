"""Opt-in MCP schemas for the native Part Family bridge commands."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

FamilyValue = StrictStr | StrictInt | StrictFloat | StrictBool


def add_part_family_tools(
    mcp: MCPServer, call: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
) -> None:
    @mcp.tool()
    async def nx_get_part_family(
        part_name: str | None = None,
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=200)] = 100,
    ) -> dict[str, Any]:
        """EXPERIMENTAL: Read columns and ordered members of an open native Part Family.

        part_name selects one open part by filename, name or full path; omitted uses
        the work part. Paginate with offset/limit. Values retain NX expression strings.
        """
        return await call(
            "nx_get_part_family",
            {
                "part_name": part_name,
                "offset": offset,
                "limit": limit,
            },
        )

    @mcp.tool()
    async def nx_add_part_family_member(
        member_name: str,
        values: dict[str, FamilyValue],
        part_name: str | None = None,
        copy_from: str = "last",
        other_name: str | None = None,
        save: bool = False,
    ) -> dict[str, Any]:
        """EXPERIMENTAL: Copy a native family member and override named table columns.

        Read nx_get_part_family first. copy_from is 'last' or an exact member name.
        member_name is the new native member name (OS_PART_NAME); other_name supplies
        the DB identity for importable templates, defaulting to member_name.
        Identity columns cannot be overridden via values. save=True saves the template;
        otherwise the entry remains in session. Does not generate a child .prt or apply
        its parameters to template geometry. Native workspace parts only.
        """
        return await call(
            "nx_add_part_family_member",
            {
                "part_name": part_name,
                "copy_from": copy_from,
                "member_name": member_name,
                "other_name": other_name,
                "values": values,
                "save": save,
            },
        )
