# Native Part Family tools

These experimental commands edit an existing native Part Family table. They do
not generate member `.prt` files or apply a member's values to template geometry.
Teamcenter-managed families and creating the first row of an empty family are
outside this version's scope.

## Discover the family

Call `nx_get_part_family` with the name or full path of an already open template:

```json
{
  "part_name": "Hex-Socket-Set-Screw-Cup-Point-DIN.prt",
  "offset": 0,
  "limit": 100
}
```

Omitting `part_name` selects NX's work part. The response includes ordered member
names, column names and NX attribute types, and each row's values. Values are
strings because NX permits expressions as well as numbers. `next_offset` enables
pagination; null means the final page. The maximum page size is 200.

## Copy and add a row

After checking the column names and existing member identities, call
`nx_add_part_family_member`, for example:

```json
{
  "part_name": "Hex-Socket-Set-Screw-Cup-Point-DIN.prt",
  "copy_from": "last",
  "member_name": "M24x100",
  "values": {"SCREW_LENGTH": 100},
  "save": true
}
```

The example name must be replaced with a valid, unused name appropriate to the
actual family. `copy_from` accepts `last` or an exact existing member name.
Unspecified nonidentity columns retain their source values. `values` accepts any
column names found in the table, with string, finite number or boolean values;
booleans become NX strings `1`/`0`. Numeric attribute types receive numeric
validation; expression columns also accept expression strings.

Identity columns use `member_name` and `other_name`, rather than `values`.
For native importable families, `member_name` is the OS member name and
`other_name` supplies the second identity requested by NX, defaulting to the
new member name. Duplicate identities and unknown columns fail before adding
a row. All selected parts must be inside the configured NX workspace.

`save` defaults to false, leaving the row in the open NX session. True also saves
the template part. A row-edit failure attempts an NX undo rollback. If saving
fails after the row was added, `NX_FAMILY_SAVE_FAILED` explicitly reports that
the row remains in session; inspect it before retrying. The returned `generated`
field is always false. Editing a table and generating its member files are
separate NX operations.

## Activation

1. Set `NX_MCP_ENABLE_EXPERIMENTAL=1` in the MCP sidecar configuration.
2. Restart the sidecar so clients can discover the new tools.
3. For the interactive GUI bridge, build and load a fresh DLL. A bridge already
   running from an older DLL does not gain commands automatically. Build into a
   different directory when the old DLL is locked by NX:

   ```powershell
   .\nx_gui_bridge\build.ps1 -NxRoot 'C:\Program Files\Siemens\NX2312' -OutputDirectory '.\nx_gui_bridge\build-part-family'
   ```

   Stop the existing bridge by executing its DLL again, then load the newly built
   DLL through File > Execute > NX Open. Follow [GUI bridge](gui-bridge.md) for
   matching workspace/state directory configuration. Do not run two bridges
   against the same descriptor.
4. For the batch Python bridge, restart its runner with the updated source and
   `NX_MCP_ENABLE_EXPERIMENTAL=1` in its own environment as well.

## Implementation and evidence

The MCP schema is stable: `values` is a dictionary. Its keys vary by family.
The executor discovers the actual columns from NX on every call and validates
the dictionary against those columns. No screw-specific schema or column list
is embedded in the tool.

`part_family_tools.py` defines the public tools, `part_family.py` implements the
Python NX operations, and `NxMcpGuiBridge.cs` implements the same operations for
the interactive bridge. The implementation uses NXOpen `TemplateManager`,
`GetChosenAttributes`, `GetInstanceDefinition`, `AddInstanceDefinition` and
`SavePartFamily`. The default 16-tool surface remains unchanged.

Local tests cover dynamic MCP arguments, source-row copying, pagination,
identities, workspace confinement, invalid values, rollback and save failure.
The full C# DLL compiles against the installed NX2312 assemblies. These checks
are not real-NX acceptance of the new commands; validate them on a disposable
family template before production use.
