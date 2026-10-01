"""Eval harness: extraction accuracy before/after verify, and anomaly precision/recall.

Runs extract -> verify -> anomaly detection over every email in data/sample_emails/
and compares against data/ground_truth.csv and data/anomaly_labels.csv.
Side-effect free: nothing is written to the sheet or to vendor history. Anomalies
are judged against data/history_seed.json at each label row's `as_of` date.

Gemini is called in batches: every uncached email goes out in ONE request, and
every re-extraction verify asks for in one more, so a full run costs at most two
requests. Results are cached per email in data/.cache/extractions.jsonl, keyed on
model, email text, verify hint, and the extraction prompt/schema, so re-runs only
pay for new or edited emails.

Usage:
    python eval.py                     # Gemini (GEMINI_API_KEY, or Vertex via GOOGLE_CLOUD_PROJECT)
    python eval.py --no-cache          # force fresh Gemini calls
    python eval.py --extractor regex   # offline no-LLM baseline, no key needed
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import date

from dotenv import load_dotenv

load_dotenv()
# Labels and data/history_seed.json were made with the static FX table; live rates would drift the scores.
os.environ["FX_SOURCE"] = "static"

from agent.parsing import FIELDS, regex_extract, vendor_key  # noqa: E402  (import after env is loaded)
from agent.schemas import BatchInvoice  # noqa: E402
from agent.tools import _MODEL, EXTRACT_PROMPT, RETRY_PROMPT, _extract_many, _get_client, batched, detect_anomalies, load_sample_emails, verify_many  # noqa: E402

CACHE_PATH = "data/.cache/extractions.jsonl"


def _cached(extract_many, path: str | None = CACHE_PATH):
    """Wrap the batch Gemini extractor so each (model, prompt, email, hint) is paid for once.

    Only cache misses are sent, all in one request. Returns (wrapped, stats) where
    stats counts cache hits, newly extracted emails, and Gemini requests. path=None
    skips reading and writing the cache file.
    """
    # Editing the prompts or the schema changes this, invalidating old entries.
    version = EXTRACT_PROMPT + RETRY_PROMPT + json.dumps(BatchInvoice.model_json_schema(), sort_keys=True)
    cache, stats = {}, {"hits": 0, "calls": 0, "requests": 0}
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    cache[row["key"]] = row["record"]
                except (json.JSONDecodeError, KeyError):  # e.g. a line cut off by a crash
                    continue
        with open(path, "rb+") as f:  # end a cut-off last line so the next append starts fresh
            f.seek(0, os.SEEK_END)
            if f.tell():
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    f.write(b"\n")

    def run(email_texts: list[str], hints: list[str] | None = None) -> list:
        hints = hints or [""] * len(email_texts)
        keys = [hashlib.sha256("\0".join([_MODEL, version, h, t]).encode()).hexdigest()
                for t, h in zip(email_texts, hints)]
        misses = [i for i, k in enumerate(keys) if k not in cache]
        stats["hits"] += len(keys) - len(misses)
        fresh = {}
        if misses:
            stats["requests"] += -(-len(misses) // int(os.environ.get("GEMINI_BATCH_SIZE", "25")))
            fresh = dict(zip(misses, extract_many([email_texts[i] for i in misses], [hints[i] for i in misses])))
            done = {i: r for i, r in fresh.items() if isinstance(r, dict)}  # failures are retried next run
            stats["calls"] += len(done)
            cache.update({keys[i]: r for i, r in done.items()})
            if path and done:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "a", encoding="utf-8") as f:
                    for i, record in done.items():
                        f.write(json.dumps({"key": keys[i], "model": _MODEL, "record": record}) + "\n")
        return [fresh[i] if i in fresh else dict(cache[k]) for i, k in enumerate(keys)]

    return run, stats


def _read_csv(path: str) -> dict[str, dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return {row["file"]: row for row in csv.DictReader(f)}


def _field_ok(field: str, got, want: str) -> bool:
    """Match rules: amount within 0.01; vendor equal or contained after normalizing; booleans as booleans; others exact."""
    if field == "amount":
        return got is not None and abs(float(got) - float(want)) < 0.01
    if field == "currency":
        return (got or "").upper() == want.upper()
    if field == "vendor":
        g, w = vendor_key(got), vendor_key(want)
        return len(g) >= 3 and (g == w or g in w or w in g)
    if field in ("paid", "autopay"):
        return bool(got) == (want.strip().lower() in ("true", "1", "yes"))
    return (got or "") == (want or "")


def _pct(k: int, n: int) -> str:
    return f"{k}/{n} ({100 * k / n:.0f}%)" if n else "n/a"


def _ratio(num: int, den: int) -> str:
    return f"{num / den:.2f}" if den else "n/a"


def _table(headers: list[str], rows: list[list]) -> None:
    widths = [max(len(str(c)) for c in col) for col in zip(headers, *rows)]
    fmt = lambda r: "| " + " | ".join(str(c).ljust(w) for c, w in zip(r, widths)) + " |"  # noqa: E731
    print(fmt(headers))
    print("|" + "|".join("-" * (w + 2) for w in widths) + "|")
    for r in rows:
        print(fmt(r))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extractor", choices=["gemini", "regex"], default="gemini")
    parser.add_argument("--history", default="data/history_seed.json")
    parser.add_argument("--no-cache", action="store_true", help="ignore cached Gemini extractions")
    args = parser.parse_args()
    extractor, cache_stats = batched(regex_extract), None
    if args.extractor == "gemini":
        try:
            _get_client()
        except RuntimeError as exc:
            parser.error(f"{exc}; or run offline with --extractor regex")
        extractor, cache_stats = _cached(_extract_many, None if args.no_cache else CACHE_PATH)

    truth = _read_csv("data/ground_truth.csv")
    labels = _read_csv("data/anomaly_labels.csv")
    with open(args.history, encoding="utf-8") as f:
        seed = json.load(f)
    inbox = load_sample_emails()
    emails = [e for e in inbox if e["id"] in truth]
    fields = [f for f in FIELDS if f in next(iter(truth.values()))]

    before = {f: 0 for f in fields} | {"ALL FIELDS": 0}
    after = dict(before)
    counts = {kind: [0, 0, 0] for kind in ("overdue", "above_trend", "any flag")}  # tp, fp, fn
    corrected = review = labelled = 0
    details, errors = [], []

    texts = [e["text"] for e in emails]
    try:
        firsts = extractor(texts)
        finals = verify_many(firsts, texts, extractor)
    except Exception as exc:  # the batch request itself failed: nothing to score
        sys.exit(f"Extraction request failed: {type(exc).__name__}: {exc}")

    for email, first, final in zip(emails, firsts, finals):
        gt = truth[email["id"]]
        if isinstance(final, Exception):  # reported separately, not scored
            errors.append(f"{email['id']}: {type(final).__name__}: {final}")
            continue
        for tally, rec in ((before, first), (after, final)):
            oks = [_field_ok(f, rec.get(f), gt[f]) for f in fields]
            for f, ok in zip(fields, oks):
                tally[f] += ok
            tally["ALL FIELDS"] += all(oks)
        corrected += final["corrected"]
        review += final["needs_review"]
        wrong = [f"{f}={final.get(f)!r} (want {gt[f]!r})" for f in fields if not _field_ok(f, final.get(f), gt[f])]

        flags = "-"
        if label := labels.get(email["id"]):
            labelled += 1
            pred = detect_anomalies(final, seed.get(vendor_key(final["vendor"]), []), date.fromisoformat(label["as_of"]))
            want_overdue, want_above = label["overdue"] == "1", label["above_trend"] == "1"
            for kind, p, w in (("overdue", pred["overdue"], want_overdue),
                               ("above_trend", pred["above_trend"], want_above),
                               ("any flag", pred["flagged"], want_overdue or want_above)):
                counts[kind][0] += p and w
                counts[kind][1] += p and not w
                counts[kind][2] += w and not p
            flags = "; ".join(pred["reasons"]) or "none"
        details.append([email["id"], "; ".join(wrong) or "all correct", "yes" if final["corrected"] else "no", flags])

    n = len(emails) - len(errors)
    if errors:
        print(f"\n{len(errors)} of {len(emails)} emails FAILED and are excluded from the scores below:")
        print("\n".join(f"  {e}" for e in errors))
    if not n:
        sys.exit("No emails were scored; fix the errors above and re-run.")
    model = f", model={_MODEL}" if args.extractor == "gemini" else ""
    cache = (f", cache: {cache_stats['hits']} hits / {cache_stats['calls']} newly extracted"
             f" in {cache_stats['requests']} Gemini request(s)") if cache_stats else ""
    print(f"\nExtraction accuracy  (extractor={args.extractor}{model}, n={n} scored emails{cache})\n")
    _table(["Field", "Before verify", "After verify"],
           [[f, _pct(before[f], n), _pct(after[f], n)] for f in before])
    print(f"\nverify: {corrected} record(s) corrected by re-extraction, {review} still flagged needs_review")

    print(f"\nAnomaly detection  (n={labelled} labelled, history={args.history})\n")
    _table(["Type", "TP", "FP", "FN", "Precision", "Recall"],
           [[k, tp, fp, fn, _ratio(tp, tp + fp), _ratio(tp, tp + fn)] for k, (tp, fp, fn) in counts.items()])

    print("\nPer email (after verify)\n")
    _table(["File", "Field errors", "Corrected", "Flags"], details)
    unlabelled = sorted({e["id"] for e in inbox} - set(truth))
    missing = sorted(set(truth) - {e["id"] for e in inbox})
    for msg in [f"no ground truth for {f}" for f in unlabelled] + [f"missing email {f}" for f in missing]:
        print(f"WARNING: {msg}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
