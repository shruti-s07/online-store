#!/usr/bin/env python
"""Online Store Database - one cross-platform CLI.

    python store.py setup      install deps, create .env, check PostgreSQL, migrate
    python store.py seed       fill the database with the synthetic history (--reset to wipe)
    python store.py train      train every model and write ai/models/REPORT.md
    python store.py api        run the REST API (Swagger at /api/docs/)
    python store.py jobs       run background jobs (APScheduler)
    python store.py ui         start the desktop client
    python store.py test       run the test suite (extra args go to pytest)
    python store.py screenshots  render every UI screen offscreen into docs/screenshots/
                                 (--record-fixtures also records ui/fixtures/ for UI_MOCK_MODE)
"""
from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIN_PY = (3, 12)


def _django():
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()


def _ensure_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        return
    text = (ROOT / "config" / ".env.example").read_text(encoding="utf-8")
    text = text.replace("DJANGO_SECRET_KEY=change-me", f"DJANGO_SECRET_KEY={secrets.token_urlsafe(50)}", 1)
    env.write_text(text, encoding="utf-8")
    print(f"Created {env} from config/.env.example - edit DB_PASSWORD and the SEED_* passwords before seeding.")


def _check_db() -> bool:
    import psycopg

    from config.loader import env
    params = dict(dbname=env("DB_NAME"), user=env("DB_USER"), password=env("DB_PASSWORD"), host=env("DB_HOST"),
                  port=env("DB_PORT"), connect_timeout=env("DB_CONNECT_TIMEOUT", cast=int))
    try:
        with psycopg.connect(**params) as conn:
            mc = conn.execute("SHOW max_connections").fetchone()[0]
            print(f"PostgreSQL OK ({env('DB_HOST')}:{env('DB_PORT')}/{env('DB_NAME')}, max_connections={mc})")
            if int(mc) <= 105:
                print("  note: the concurrency test needs max_connections > 105 (see README).")
            return True
    except psycopg.OperationalError as exc:
        admin, admin_pw = env("DB_ADMIN_USER", ""), env("DB_ADMIN_PASSWORD", "")
        if not admin:
            print(f"Cannot connect to PostgreSQL: {exc}\nStart PostgreSQL (docker compose up -d, or a local "
                  "install) and check DB_* in .env. See README.md.")
            return False
        print("Database not reachable as app user; creating role/database with DB_ADMIN_USER ...")
        from psycopg import sql
        with psycopg.connect(dbname="postgres", user=admin, password=admin_pw, host=params["host"],
                             port=params["port"], autocommit=True) as conn:
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (params["user"],)).fetchone():
                conn.execute(sql.SQL("CREATE ROLE {} LOGIN CREATEDB PASSWORD {}").format(
                    sql.Identifier(params["user"]), sql.Literal(params["password"])))
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (params["dbname"],)).fetchone():
                conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(params["dbname"]), sql.Identifier(params["user"])))
        return _check_db()


def cmd_setup(a):
    if sys.version_info < MIN_PY:
        sys.exit(f"Python {MIN_PY[0]}.{MIN_PY[1]}+ is required (found {sys.version.split()[0]}).")
    if not a.no_install:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    _ensure_env()
    sys.path.insert(0, str(ROOT))
    if not _check_db():
        sys.exit(1)
    _django()
    from django.conf import settings
    from django.core.management import call_command
    call_command("migrate", interactive=False)
    Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
    print("Setup complete. Next: python store.py seed && python store.py train")


def cmd_seed(a):
    _django()
    from django.core.management import call_command
    args = ["--reset"] if a.reset else []
    call_command("seed_store", *args, "--scale", str(a.scale))


def cmd_train(a):
    _django()
    from ai.train import train_all
    result = train_all(a.only.split(",") if a.only else None)
    print(f"Training finished: {result}. Report: ai/models/REPORT.md")


def cmd_api(a):
    _django()
    from django.core.management import call_command

    from config.loader import env
    print(f"API on http://{env('API_HOST')}:{env('API_PORT')}/api/  (Swagger: /api/docs/)")
    call_command("runserver", f"{env('API_HOST')}:{env('API_PORT')}", use_reloader=False)


def cmd_jobs(a):
    _django()
    import logging
    logging.getLogger("jobs").setLevel(logging.INFO)
    if a.once:
        from backend.folder_two_services.jobs.runner import JOBS
        run = JOBS[a.once]()
        print(run.status, run.detail)
        return
    from backend.folder_two_services.jobs.scheduler import run_forever
    run_forever()


def cmd_ui(a):
    sys.path.insert(0, str(ROOT))
    from ui.main import main
    sys.exit(main())


def cmd_test(a):
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", *a.pytest_args], cwd=ROOT))


def cmd_screenshots(a):
    os.environ["QT_QPA_PLATFORM"] = a.platform
    sys.path.insert(0, str(ROOT))
    from ui.screenshots import main
    sys.exit(main(record_fixtures=a.record_fixtures))


def main():
    p = argparse.ArgumentParser(prog="store.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup"); s.add_argument("--no-install", action="store_true"); s.set_defaults(fn=cmd_setup)
    s = sub.add_parser("seed"); s.add_argument("--reset", action="store_true")
    s.add_argument("--scale", type=float, default=1.0); s.set_defaults(fn=cmd_seed)
    s = sub.add_parser("train"); s.add_argument("--only", help="comma list, e.g. fraud,sentiment"); s.set_defaults(fn=cmd_train)
    sub.add_parser("api").set_defaults(fn=cmd_api)
    s = sub.add_parser("jobs"); s.add_argument("--once", help="run one job now and exit"); s.set_defaults(fn=cmd_jobs)
    sub.add_parser("ui").set_defaults(fn=cmd_ui)
    s = sub.add_parser("test"); s.add_argument("pytest_args", nargs=argparse.REMAINDER); s.set_defaults(fn=cmd_test)
    s = sub.add_parser("screenshots"); s.add_argument("--platform", default="offscreen")
    s.add_argument("--record-fixtures", action="store_true", help="also record ui/fixtures/ for UI_MOCK_MODE")
    s.set_defaults(fn=cmd_screenshots)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
