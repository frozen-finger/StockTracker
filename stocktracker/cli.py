from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from stocktracker.http import HttpClient
from stocktracker.pipeline import run_pipeline, write_report
from stocktracker.sources.bing_news import BingNewsCollector
from stocktracker.sources.cninfo import CninfoCollector


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect weekly A-share ownership/governance events")
    parser.add_argument("--days", type=int, default=8, help="Inclusive lookback window in days")
    parser.add_argument("--end-date", type=date.fromisoformat, help="Window end in YYYY-MM-DD")
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--timeout", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.days < 1 or args.days > 31:
        raise SystemExit("--days must be between 1 and 31")
    end = args.end_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    start = end - timedelta(days=args.days - 1)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    http = HttpClient(timeout=args.timeout)
    collectors = [CninfoCollector(http), BingNewsCollector(http)]
    report = run_pipeline(collectors, start, end)
    latest, snapshot = write_report(report, args.output_dir)
    logging.info("Wrote %s and %s (%s documents, status=%s)", latest, snapshot, report["stats"]["document_count"], report["status"])
    return 0 if report["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
