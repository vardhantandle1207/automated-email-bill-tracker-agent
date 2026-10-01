"""Day 1 test harness.

Runs extract_invoice directly over every sample email (no agent loop yet) and
prints the extracted + normalized fields. This is what you eyeball on Day 1 to
confirm extraction works before you build the eval harness on Day 2.

Usage:
    python run_day1.py
"""

import glob
import os

from dotenv import load_dotenv

load_dotenv()  # read GEMINI_API_KEY from .env

from agent.tools import extract_invoice  # noqa: E402  (import after env is loaded)


def main() -> None:
    paths = sorted(glob.glob("data/sample_emails/*.txt"))
    if not paths:
        print("No sample emails in data/sample_emails/")
        return
    for path in paths:
        with open(path, encoding="utf-8") as f:
            email_text = f.read()
        result = extract_invoice(email_text)
        print(f"\n=== {os.path.basename(path)} ===")
        for key, value in result.items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
