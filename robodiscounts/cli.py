import argparse
import logging
import os
import sys
import time
from pathlib import Path

from .checker import run_once
from .config import load_config
from .dashboard import render
from .notifier import ConsoleNotifier, WhatsAppNotifier
from .store import Store


def main():
    ap = argparse.ArgumentParser(prog="robodiscounts")
    ap.add_argument("command", choices=["check", "watch", "test-message", "dashboard"])
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("-o", "--output", default="site/index.html", help="dashboard output file")
    ap.add_argument("--dry-run", action="store_true", help="print instead of sending WhatsApp")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    try:  # optional .env support
        env = Path(".env")
        if env.exists():
            for line in env.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass

    if args.command == "dashboard":  # needs no WhatsApp credentials
        cfg = load_config(args.config)
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(cfg, Store(cfg.db_path)), encoding="utf-8")
        print(f"Dashboard written to {out}")
        return

    notifier = ConsoleNotifier() if args.dry_run else WhatsAppNotifier()
    if args.command == "test-message":
        notifier.send("✅ robodiscounts is connected.")
        return

    cfg = load_config(args.config)
    store = Store(cfg.db_path)
    if args.command == "check":
        summary = run_once(cfg, store, notifier)
        if summary.all_failed:
            logging.error("All %d items failed to load; exiting with error", summary.checked)
            sys.exit(1)
    else:
        while True:
            run_once(cfg, store, notifier)
            time.sleep(cfg.check_interval_minutes * 60)


if __name__ == "__main__":
    main()
