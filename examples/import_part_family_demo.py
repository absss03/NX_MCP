"""Example: Batch import Part Family members from a Pandas DataFrame or Excel file.

This external script connects to a running Siemens NX session via the NX MCP bridge
and registers new family members defined in a DataFrame or Excel file.

Requirements:
- Siemens NX running with the NX MCP bridge loaded (GUI bridge DLL or Python runner).
- pip install pandas openpyxl (if using Excel / DataFrames)
"""

from __future__ import annotations

from nx_mcp.part_family_importer import (
    import_part_family_from_dataframe,
    import_part_family_from_file,
)


def demo_with_dataframe():
    try:
        import pandas as pd
    except ImportError:
        print("Pandas is not installed. Run: pip install pandas")
        return

    # 1. Define or load your data in a pandas DataFrame
    data = {
        "member_name": ["M12x50", "M12x60", "M12x70"],
        "SCREW_LENGTH": [50, 60, 70],
        "DIAMETER": [12, 12, 12],
        "THREAD_PITCH": [1.75, 1.75, 1.75],
    }
    df = pd.DataFrame(data)

    print("Data to import:")
    print(df)

    # 2. Import into the active Part Family in NX
    print("\nImporting into NX...")
    result = import_part_family_from_dataframe(
        df,
        part_name=None,  # None selects the active work part in NX
        copy_from="last",  # Inherits other columns from the last existing row
        save=True,  # Save the part in NX after importing
        dry_run=False,  # Set to True to preview without making changes
        on_progress=lambda idx, total, name, status: print(f"[{idx}/{total}] {name}: {status}"),
    )

    print("\nResult summary:")
    print(f"Added: {len(result.added)} members")
    print(f"Skipped: {len(result.skipped)} members")
    print(f"Failed: {len(result.failed)} members")


def demo_with_excel_or_csv():
    file_path = "tornillos.xlsx"  # or "tornillos.csv"

    print(f"\nImporting from file: {file_path}")
    result = import_part_family_from_file(
        file_path,
        part_name=None,
        save=True,
        on_progress=lambda idx, total, name, status: print(f"[{idx}/{total}] {name}: {status}"),
    )
    print(f"Added {len(result.added)} members from file.")


if __name__ == "__main__":
    demo_with_dataframe()
