"""External utility and CLI to batch import Part Family members from Excel or DataFrames.

This tool runs as an external process (outside NX) and communicates with the
running Siemens NX session via the local NX MCP bridge.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nx_mcp.bridge import DescriptorBridgeClient
from nx_mcp.runtime import NXToolError

IDENTITY_COLUMN_CANDIDATES = [
    "member_name",
    "member",
    "os_part_name",
    "part_name",
    "partname",
    "part_no",
    "nombre",
    "miembro",
]

OTHER_NAME_CANDIDATES = [
    "other_name",
    "db_part_no",
    "db_part_name",
    "part_number",
    "codigo",
    "referencia",
]


@dataclass
class ImportResult:
    """Summary of the Part Family import execution."""

    part_name: str
    part_path: str
    total_rows: int
    added: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    saved: bool = False

    @property
    def is_success(self) -> bool:
        return len(self.failed) == 0


def _clean_value(val: Any) -> Any | None:
    """Normalize cell values; return None if empty/NaN."""
    if val is None:
        return None
    if isinstance(val, float):
        if math.isnan(val) or not math.isfinite(val):
            return None
        # Convert whole floats (e.g. 100.0) to int for cleaner strings
        if val.is_integer():
            return int(val)
        return val
    if isinstance(val, str):
        stripped = val.strip()
        if not stripped or stripped.lower() in {"nan", "none", "null", ""}:
            return None
        return stripped
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return val
    # Fallback to string
    return str(val).strip()


def parse_data_file(
    file_path: str | Path, sheet_name: str | int | None = None
) -> list[dict[str, Any]]:
    """Parse an Excel (.xlsx, .xls) or CSV file into a list of row dictionaries."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()

    if suffix == ".csv":
        with path.open(mode="r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]

    if suffix in {".xlsx", ".xls"}:
        # Check for pandas first
        try:
            import pandas as pd  # type: ignore

            df = pd.read_excel(path, sheet_name=sheet_name if sheet_name is not None else 0)
            return df.to_dict(orient="records")
        except ImportError:
            pass

        # Try openpyxl directly
        try:
            import openpyxl  # type: ignore

            wb = openpyxl.load_workbook(path, data_only=True)
            sheet = wb[sheet_name] if isinstance(sheet_name, str) else wb.worksheets[sheet_name or 0]
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                return []
            headers = [str(h).strip() if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
            result = []
            for row in rows[1:]:
                if any(v is not None for v in row):
                    result.append(dict(zip(headers, row, strict=False)))
            return result
        except ImportError as err:
            raise ImportError(
                "Reading Excel files requires 'pandas' or 'openpyxl'. "
                "Install them via 'pip install pandas openpyxl' or provide a .csv file."
            ) from err

    raise ValueError(f"Unsupported file format: {suffix}. Supported: .xlsx, .xls, .csv")


def _find_column(candidates: list[str], available_columns: list[str]) -> str | None:
    avail_lower = {col.casefold(): col for col in available_columns}
    for cand in candidates:
        if cand.casefold() in avail_lower:
            return avail_lower[cand.casefold()]
    return None


async def async_import_part_family(
    rows: list[dict[str, Any]],
    part_name: str | None = None,
    *,
    member_col: str | None = None,
    other_col: str | None = None,
    copy_from: str = "last",
    save: bool = False,
    skip_existing: bool = True,
    dry_run: bool = False,
    client: Any | None = None,
    on_progress: Any | None = None,
) -> ImportResult:
    """Import rows into an open native Part Family via NX bridge."""
    if not rows:
        raise ValueError("No rows provided to import.")

    bridge = client or DescriptorBridgeClient()

    # 1. Fetch current family definition
    family = await bridge.call("nx_get_part_family", {"part_name": part_name})
    active_part_name = family.get("part_name", part_name or "active_part")
    active_part_path = family.get("part_path", "")

    existing_members = {m["member_name"] for m in family.get("members", [])}
    nx_columns = family.get("columns", [])
    nx_col_names = {col["name"]: col for col in nx_columns}

    # Discover member and other columns if not specified
    sample_row = rows[0]
    row_keys = list(sample_row.keys())

    resolved_member_col = member_col or _find_column(IDENTITY_COLUMN_CANDIDATES, row_keys)
    if not resolved_member_col:
        # Fallback to the first column if no candidate matches
        resolved_member_col = row_keys[0]

    resolved_other_col = other_col or _find_column(OTHER_NAME_CANDIDATES, row_keys)

    # Filter columns that correspond to NX attributes (excluding identity columns)
    identity_names = {"OS_PART_NAME", "DB_PART_NO", "DB_PART_NAME"}
    valid_attribute_columns = {
        col_name for col_name in nx_col_names
        if col_name not in identity_names and str(nx_col_names[col_name].get("type", "")).split(".")[-1] != "Name"
    }

    result = ImportResult(
        part_name=active_part_name,
        part_path=active_part_path,
        total_rows=len(rows),
    )

    total = len(rows)
    for idx, row in enumerate(rows, start=1):
        raw_member = row.get(resolved_member_col)
        cleaned_member = _clean_value(raw_member)
        if not cleaned_member:
            result.skipped.append((f"Row {idx}", f"Missing member name in column '{resolved_member_col}'"))
            continue

        member_name = str(cleaned_member).strip()

        # Check existing
        if member_name in existing_members:
            if skip_existing:
                result.skipped.append((member_name, "Already exists in Part Family"))
                if on_progress:
                    on_progress(idx, total, member_name, "skipped (exists)")
                continue
            else:
                result.failed.append((member_name, "Duplicate member name rejected"))
                if on_progress:
                    on_progress(idx, total, member_name, "failed (duplicate)")
                continue

        # Extract other_name if available
        other_name = None
        if resolved_other_col and resolved_other_col in row:
            val = _clean_value(row[resolved_other_col])
            if val is not None:
                other_name = str(val).strip()

        # Build attribute values to override
        values: dict[str, Any] = {}
        for key, val in row.items():
            if key in (resolved_member_col, resolved_other_col):
                continue
            # Check if key matches an NX column (case-insensitively or exact)
            matched_nx_col = None
            if key in valid_attribute_columns:
                matched_nx_col = key
            else:
                for col in valid_attribute_columns:
                    if col.casefold() == str(key).casefold():
                        matched_nx_col = col
                        break

            if matched_nx_col:
                cleaned_val = _clean_value(val)
                if cleaned_val is not None:
                    values[matched_nx_col] = cleaned_val

        if dry_run:
            result.added.append(member_name)
            existing_members.add(member_name)
            if on_progress:
                on_progress(idx, total, member_name, f"[DRY-RUN] Would add with {len(values)} overridden attributes")
            continue

        # Determine whether to save with this member (save on the very last added row if save=True)
        is_last_item = (idx == total)
        should_save = save and is_last_item

        try:
            params: dict[str, Any] = {
                "part_name": part_name,
                "copy_from": copy_from,
                "member_name": member_name,
                "values": values,
                "save": should_save,
            }
            if other_name:
                params["other_name"] = other_name

            await bridge.call("nx_add_part_family_member", params)
            result.added.append(member_name)
            existing_members.add(member_name)
            if should_save:
                result.saved = True
            if on_progress:
                on_progress(idx, total, member_name, "added successfully")
        except NXToolError as err:
            result.failed.append((member_name, err.message))
            if on_progress:
                on_progress(idx, total, member_name, f"failed: {err.message}")
        except Exception as err:
            result.failed.append((member_name, str(err)))
            if on_progress:
                on_progress(idx, total, member_name, f"error: {err}")

    # If save was requested but the last row was skipped/failed, perform a standalone save if any added
    if save and not result.saved and result.added and not dry_run:
        try:
            # We can invoke nx_save_part or save through the bridge
            await bridge.call("nx_save_part", {"path": active_part_path} if active_part_path else {})
            result.saved = True
        except Exception:
            pass

    return result


def import_part_family_from_dataframe(
    df: Any,
    part_name: str | None = None,
    *,
    member_col: str | None = None,
    other_col: str | None = None,
    copy_from: str = "last",
    save: bool = False,
    skip_existing: bool = True,
    dry_run: bool = False,
    client: Any | None = None,
    on_progress: Any | None = None,
) -> ImportResult:
    """Synchronous helper to import from a pandas DataFrame."""
    rows = df.to_dict(orient="records")
    return asyncio.run(
        async_import_part_family(
            rows=rows,
            part_name=part_name,
            member_col=member_col,
            other_col=other_col,
            copy_from=copy_from,
            save=save,
            skip_existing=skip_existing,
            dry_run=dry_run,
            client=client,
            on_progress=on_progress,
        )
    )


def import_part_family_from_file(
    file_path: str | Path,
    part_name: str | None = None,
    *,
    sheet_name: str | int | None = None,
    member_col: str | None = None,
    other_col: str | None = None,
    copy_from: str = "last",
    save: bool = False,
    skip_existing: bool = True,
    dry_run: bool = False,
    client: Any | None = None,
    on_progress: Any | None = None,
) -> ImportResult:
    """Synchronous helper to import from an Excel (.xlsx/.xls) or .csv file."""
    rows = parse_data_file(file_path, sheet_name=sheet_name)
    return asyncio.run(
        async_import_part_family(
            rows=rows,
            part_name=part_name,
            member_col=member_col,
            other_col=other_col,
            copy_from=copy_from,
            save=save,
            skip_existing=skip_existing,
            dry_run=dry_run,
            client=client,
            on_progress=on_progress,
        )
    )


def main() -> None:
    """Command-line interface for the Part Family external importer."""
    parser = argparse.ArgumentParser(
        description="External tool to batch import Part Family members into Siemens NX from Excel/CSV."
    )
    parser.add_argument("-f", "--file", required=True, help="Path to input Excel (.xlsx, .xls) or CSV file")
    parser.add_argument("-p", "--part", default=None, help="Name or path of the open template part in NX (default: work part)")
    parser.add_argument("-s", "--sheet", default=None, help="Sheet name or index if using Excel")
    parser.add_argument("-m", "--member-col", default=None, help="Column name to use as member name (OS_PART_NAME)")
    parser.add_argument("-o", "--other-col", default=None, help="Column name for other_name / DB_PART_NO")
    parser.add_argument("-c", "--copy-from", default="last", help="Source member name to copy base values from (default: 'last')")
    parser.add_argument("--save", action="store_true", help="Save the template part in NX after import")
    parser.add_argument("--dry-run", action="store_true", help="Validate input and preview changes without modifying NX")
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false", help="Fail instead of skipping if member name exists")
    parser.set_defaults(skip_existing=True)

    args = parser.parse_args()

    def progress_logger(idx: int, total: int, member: str, status: str) -> None:
        print(f"[{idx}/{total}] {member}: {status}")

    print(f"Loading input file: {args.file}...")
    try:
        result = import_part_family_from_file(
            file_path=args.file,
            part_name=args.part,
            sheet_name=args.sheet,
            member_col=args.member_col,
            other_col=args.other_col,
            copy_from=args.copy_from,
            save=args.save,
            skip_existing=args.skip_existing,
            dry_run=args.dry_run,
            on_progress=progress_logger,
        )
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\n--- Summary ---")
    print(f"Part: {result.part_name} ({result.part_path})")
    print(f"Total Rows: {result.total_rows}")
    print(f"Added: {len(result.added)}")
    print(f"Skipped: {len(result.skipped)}")
    print(f"Failed: {len(result.failed)}")
    if args.dry_run:
        print("Dry Run: YES (no changes made to NX)")
    else:
        print(f"Saved: {'YES' if result.saved else 'NO'}")

    if result.failed:
        print("\nFailed rows details:")
        for name, reason in result.failed:
            print(f" - {name}: {reason}")
        sys.exit(1)


if __name__ == "__main__":
    main()
