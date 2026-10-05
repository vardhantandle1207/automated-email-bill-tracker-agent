"""OPTIONAL: keep the bill log in a Google Sheet instead of a CSV file.

Skip this file on a first read. It is only used when GOOGLE_SHEET_ID is set.
The code only reads rows and appends rows. It never edits or deletes one.
"""

import os
from functools import lru_cache

from .google_login import google_login


@lru_cache
def _cells():
    """Connect to the Google Sheets API once and reuse the connection."""
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=google_login(), cache_discovery=False).spreadsheets().values()


def read_sheet() -> list[dict]:
    """Every saved bill, as a list of {column name: value}."""
    # Step 1: Download all the cells of the first tab.
    cells = _cells().get(spreadsheetId=os.environ["GOOGLE_SHEET_ID"], range="A:J",
                         valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    if not cells:
        return []
    # Step 2: The first row holds the column names. Pair every other row with them.
    #         (Google leaves out empty cells at the end of a row, so fill those with "".)
    names = cells[0]
    return [dict(zip(names, row + [""] * (len(names) - len(row)))) for row in cells[1:]]


def append_to_sheet(columns: list[str], row: list) -> None:
    """Add one row at the bottom. An empty sheet gets the column names first."""
    sheet_id = os.environ["GOOGLE_SHEET_ID"]
    # Step 1: Is the sheet empty? Then start with the header row.
    is_empty = not _cells().get(spreadsheetId=sheet_id, range="A1").execute().get("values")
    rows = [columns, row] if is_empty else [row]
    # Step 2: Append. "RAW" stores text exactly as given, so text from an email can never run as a formula.
    _cells().append(spreadsheetId=sheet_id, range="A1", valueInputOption="RAW", body={"values": rows}).execute()
