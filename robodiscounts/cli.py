import argparse
import logging
import os
import sys
import time
from pathlib import Path

from .checker import run_once
from .config import load_config
from .dashboard import render
from .notifier import (ConfigError, ConsoleNotifier, NotificationError,
                       UnconfiguredNotifier, WhatsAppNotifier)
from .store import Store


def build_notifier(dry_run: bool):
    if dry_run:
        return ConsoleNotifier()
    try:
        return WhatsAppNotifier()
    except ConfigError as e:
        logging.warning("%s. Prices are still tracked, but alerts cannot be sent.", e)
        return UnconfiguredNotifier(str(e))


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

    if args.command == "test-message":
        try:
            notifier = ConsoleNotifier() if args.dry_run else WhatsAppNotifier()
            notifier.send("✅ robodiscounts is connected.")
        except (ConfigError, NotificationError) as e:
            print(f"Test message failed: {e}", file=sys.stderr)
            sys.exit(1)
        print("Test message sent.")
        return

    notifier = build_notifier(args.dry_run)

    cfg = load_config(args.config)
    store = Store(cfg.db_path)
    if args.command == "check":
        summary = run_once(cfg, store, notifier)
        if summary.all_failed:
            logging.error("All %d items failed to load; exiting with error", summary.checked)
        if summary.send_failed:
            logging.error("%d alert(s) could not be delivered; they will be retried next run",
                          summary.send_failed)
        if summary.all_failed or summary.send_failed:
            sys.exit(1)
    else:
        while True:
            run_once(cfg, store, notifier)
            time.sleep(cfg.check_interval_minutes * 60)


if __name__ == "__main__":
    main()
