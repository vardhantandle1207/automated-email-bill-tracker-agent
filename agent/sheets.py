"""Google Sheet backend for the bill log, used when GOOGLE_SHEET_ID is set.

Rows are read and appended. Nothing here edits or deletes a row.
"""

import os
from functools import lru_cache

from .google_login import google_login


@lru_cache
def _cells():
    """Sheets API client, built once per process."""
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=google_login(), cache_discovery=False).spreadsheets().values()


def read_sheet() -> list[dict]:
    """Every saved bill, as a list of {column name: value}."""
    cells = _cells().get(spreadsheetId=os.environ["GOOGLE_SHEET_ID"], range="A:J",
                         valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    if not cells:
        return []
    # the API drops empty trailing cells, so pad short rows before pairing with the header
    names = cells[0]
    return [dict(zip(names, row + [""] * (len(names) - len(row)))) for row in cells[1:]]


def append_to_sheet(columns: list[str], row: list) -> None:
    """Add one row at the bottom. An empty sheet gets the column names first."""
    sheet_id = os.environ["GOOGLE_SHEET_ID"]
    is_empty = not _cells().get(spreadsheetId=sheet_id, range="A1").execute().get("values")
    rows = [columns, row] if is_empty else [row]
    # RAW stores text as given, so text from an email can never run as a formula
    _cells().append(spreadsheetId=sheet_id, range="A1", valueInputOption="RAW", body={"values": rows}).execute()
