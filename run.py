"""Batch run of the full pipeline from the command line.

fetch_emails -> extract_invoice -> verify -> flag_anomalies -> log_to_sheet

Usage:
    python run.py --mock     # read data/sample_emails/ instead of Gmail
    python run.py            # Gmail (read-only); first run opens the OAuth consent page
"""

import argparse
import os

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true", help="read data/sample_emails/ instead of Gmail")
    args = parser.parse_args()
    if args.mock:
        os.environ["MOCK_INBOX"] = "1"

    from agent.pipeline import run_batch  # noqa: E402  (import after env is set)

    result = run_batch()
    for r in result["records"]:
        status = "logged" if r["logged"] else "duplicate, skipped"
        print(f"\n=== {r['source_id']} ({status}) ===")
        print(f"  {r['vendor']}: {r['amount']} {r['currency']} -> {r['amount_base']} {r['base_currency']}"
              f", due {r['due_date']}, paid={r['paid']}, autopay={r.get('autopay', False)}")
        for issue in r["issues"]:
            print(f"  NEEDS REVIEW: {issue}")
        for reason in r["reasons"]:
            print(f"  FLAG: {reason}")
    for e in result["errors"]:
        print(f"\n!!! {e['id']}: {e['error']}")


if __name__ == "__main__":
    main()
