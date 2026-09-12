from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Base, SessionFactory, make_engine
from .importer import import_evidence
from .inventory import build_inventory_snapshot
from .finance import build_financial_allocations
from .accounting import build_accounting_snapshot
from .blueprint import build_blueprints
from .foundation import build_erp_foundation
from .masters import build_canonical_masters
from .transactions import build_canonical_transactions
from .ledger import build_canonical_ledger
from .security import build_security_controls
from .coverage import build_coverage_closure
from .residuals import build_residual_workflows
from .runtime import build_runtime_foundation
from .database_copy import copy_sqlite_to_postgres
from .reconcile import reconcile_snapshot
from .transform import transform_snapshot
from .resolve import resolve_snapshot
from .delta_dry_run import run_delta_dry_run
from .delta_merge_simulation import simulate_delta_merge
from .cutover_readiness import build_cutover_readiness
from .cutover_capture import build_cutover_rehearsal
from .activity_watermark import compare_watermarks
from .capture_validation import validate_capture
from .capture_watermark import build_capture_watermark
from .erp_master_rehearsal import build_erp_master_package
from .erp_opening_rehearsal import build_erp_opening_package
from .reconciliation_refresh import build_reconciliation_refresh
from .browser_delta_staging import stage_browser_delta
from .delta_overlay import load_delta_overlay
from .models import SourceSnapshot
from .operational import initialize_operational_database, make_operational_engine
from .operational_masters import promote_operational_masters


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="klen-staging")
    root.add_argument("--database-url", help="SQLAlchemy URL; defaults to KLEN_DATABASE_URL or local SQLite")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    load = commands.add_parser("import")
    load.add_argument("--source", type=Path, required=True)
    load.add_argument("--snapshot", required=True)
    load.add_argument("--source-url", default="https://mart.bizmodo.io/")
    check = commands.add_parser("reconcile")
    check.add_argument("--snapshot", required=True)
    transform = commands.add_parser("transform")
    transform.add_argument("--snapshot", required=True)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("--snapshot", required=True)
    inventory = commands.add_parser("inventory")
    inventory.add_argument("--snapshot", required=True)
    financial = commands.add_parser("financial")
    financial.add_argument("--snapshot", required=True)
    accounting = commands.add_parser("accounting")
    accounting.add_argument("--snapshot", required=True)
    blueprint = commands.add_parser("blueprint")
    blueprint.add_argument("--snapshot", required=True)
    foundation = commands.add_parser("foundation")
    foundation.add_argument("--snapshot", required=True)
    masters = commands.add_parser("masters")
    masters.add_argument("--snapshot", required=True)
    transactions = commands.add_parser("transactions")
    transactions.add_argument("--snapshot", required=True)
    ledger = commands.add_parser("ledger")
    ledger.add_argument("--snapshot", required=True)
    security = commands.add_parser("security")
    security.add_argument("--snapshot", required=True)
    coverage = commands.add_parser("coverage")
    coverage.add_argument("--snapshot", required=True)
    residuals = commands.add_parser("residuals")
    residuals.add_argument("--snapshot", required=True)
    runtime = commands.add_parser("runtime")
    runtime.add_argument("--snapshot", required=True)
    copy_db = commands.add_parser("copy-db")
    copy_db.add_argument("--source-url", required=True,
                         help="Explicit SQLite URL; the source file is opened query-only")
    copy_db.add_argument("--batch-size", type=int, default=1000)
    delta = commands.add_parser("delta-dry-run")
    delta.add_argument("--source", type=Path, required=True)
    delta.add_argument("--output", type=Path, required=True)
    merge = commands.add_parser("delta-merge-simulate")
    merge.add_argument("--clone", type=Path, required=True)
    merge.add_argument("--delta", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)
    cutover = commands.add_parser("cutover-readiness")
    cutover.add_argument("--baseline", type=Path, required=True)
    cutover.add_argument("--delta", type=Path, required=True)
    cutover.add_argument("--clone", type=Path, required=True)
    cutover.add_argument("--delta-database", type=Path, required=True)
    cutover.add_argument("--simulation-database", type=Path, required=True)
    cutover.add_argument("--output", type=Path, required=True)
    rehearsal = commands.add_parser("cutover-rehearsal")
    rehearsal.add_argument("--baseline", type=Path, required=True)
    rehearsal.add_argument("--delta", type=Path, required=True)
    rehearsal.add_argument("--readiness", type=Path, required=True)
    rehearsal.add_argument("--output", type=Path, required=True)
    watermark = commands.add_parser("compare-watermarks")
    watermark.add_argument("--before", type=Path, required=True)
    watermark.add_argument("--after", type=Path, required=True)
    watermark.add_argument("--output", type=Path, required=True)
    capture_validation = commands.add_parser("validate-capture")
    capture_validation.add_argument("--source", type=Path, required=True)
    capture_validation.add_argument("--output", type=Path, required=True)
    capture_watermark = commands.add_parser("capture-watermark")
    capture_watermark.add_argument("--capture", type=Path, required=True)
    capture_watermark.add_argument("--before", type=Path, required=True)
    capture_watermark.add_argument("--output", type=Path, required=True)
    erp_master = commands.add_parser("erp-master-rehearsal")
    erp_master.add_argument("--capture", type=Path, required=True)
    erp_master.add_argument("--output", type=Path, required=True)
    erp_opening = commands.add_parser("erp-opening-rehearsal")
    erp_opening.add_argument("--capture", type=Path, required=True)
    erp_opening.add_argument("--baseline", type=Path, required=True)
    erp_opening.add_argument("--output", type=Path, required=True)
    refresh = commands.add_parser("reconciliation-refresh")
    refresh.add_argument("--capture", type=Path, required=True)
    refresh.add_argument("--prior-capture", type=Path, required=True)
    refresh.add_argument("--output", type=Path, required=True)
    browser_delta = commands.add_parser("browser-delta-stage")
    browser_delta.add_argument("--capture", type=Path, required=True)
    browser_delta.add_argument("--output", type=Path, required=True)
    promote_masters = commands.add_parser("promote-operational-masters")
    promote_masters.add_argument("--snapshot", required=True)
    promote_masters.add_argument("--delta-capture", type=Path)
    promote_masters.add_argument("--operational-database-url")
    promote_masters.add_argument("--actor", default="migration-controller")
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "copy-db":
        from .db import database_url
        target_url = args.database_url or database_url()
        print(json.dumps(copy_sqlite_to_postgres(args.source_url, target_url, args.batch_size),
                         indent=2, default=str))
        return
    if args.command == "delta-dry-run":
        result = run_delta_dry_run(args.source, args.output)
        print(json.dumps(result, indent=2, default=str))
        if result["status"] != "passed":
            raise SystemExit(1)
        return
    if args.command == "delta-merge-simulate":
        result = simulate_delta_merge(args.clone, args.delta, args.output)
        print(json.dumps(result, indent=2, default=str))
        if result["status"] == "failed":
            raise SystemExit(1)
        return
    if args.command == "cutover-readiness":
        result = build_cutover_readiness(
            args.baseline, args.delta, args.clone, args.delta_database,
            args.simulation_database, args.output,
        )
        print(json.dumps(result, indent=2, default=str))
        return
    if args.command == "cutover-rehearsal":
        result = build_cutover_rehearsal(args.baseline, args.delta, args.readiness, args.output)
        print(json.dumps(result, indent=2, default=str))
        return
    if args.command == "compare-watermarks":
        result = compare_watermarks(args.before, args.after, args.output)
        print(json.dumps(result, indent=2, default=str))
        if result["status"] == "activity_detected":
            raise SystemExit(1)
        return
    if args.command == "validate-capture":
        result = validate_capture(args.source, args.output)
        print(json.dumps(result, indent=2, default=str))
        if result["status"] == "failed":
            raise SystemExit(1)
        return
    if args.command == "capture-watermark":
        result = build_capture_watermark(args.capture, args.before, args.output)
        print(json.dumps(result, indent=2, default=str))
        if result["status"] == "activity_detected":
            raise SystemExit(1)
        return
    if args.command == "erp-master-rehearsal":
        result = build_erp_master_package(args.capture, args.output)
        print(json.dumps(result, indent=2, default=str))
        return
    if args.command == "erp-opening-rehearsal":
        result = build_erp_opening_package(args.capture, args.baseline, args.output)
        print(json.dumps(result, indent=2, default=str))
        return
    if args.command == "reconciliation-refresh":
        result = build_reconciliation_refresh(args.capture, args.prior_capture, args.output)
        print(json.dumps(result, indent=2, default=str))
        return
    if args.command == "browser-delta-stage":
        result = stage_browser_delta(args.capture, args.output)
        print(json.dumps(result, indent=2, default=str))
        if result["status"] == "failed":
            raise SystemExit(1)
        return
    if args.command == "promote-operational-masters":
        clone_engine = make_engine(args.database_url)
        operational_url = args.operational_database_url or os.getenv("ASAS_OPERATIONAL_DATABASE_URL")
        if not operational_url:
            raise SystemExit("ASAS_OPERATIONAL_DATABASE_URL or --operational-database-url is required")
        operational_engine = make_operational_engine(operational_url)
        initialize_operational_database(operational_engine)
        overlay = load_delta_overlay(args.delta_capture) if args.delta_capture else None
        with Session(clone_engine) as clone, Session(operational_engine) as operational:
            snapshot = clone.scalar(select(SourceSnapshot).where(SourceSnapshot.name == args.snapshot))
            if not snapshot:
                raise SystemExit(f"Snapshot not found: {args.snapshot}")
            result = promote_operational_masters(clone, operational, snapshot, overlay, actor=args.actor)
        print(json.dumps(result, indent=2, default=str))
        return
    engine = make_engine(args.database_url)
    Base.metadata.create_all(engine)
    if args.command == "init-db":
        print(json.dumps({"status": "initialized", "database": str(engine.url)}))
        return
    with SessionFactory(bind=engine) as session:
        if args.command == "import":
            result = import_evidence(session, args.source, args.snapshot, args.source_url)
            print(json.dumps(result.__dict__, indent=2))
        elif args.command == "reconcile":
            print(json.dumps(reconcile_snapshot(session, args.snapshot), indent=2, default=str))
        elif args.command == "transform":
            print(json.dumps(transform_snapshot(session, args.snapshot), indent=2, default=str))
        elif args.command == "resolve":
            print(json.dumps(resolve_snapshot(session, args.snapshot), indent=2, default=str))
        elif args.command == "inventory":
            print(json.dumps(build_inventory_snapshot(session, args.snapshot), indent=2, default=str))
        elif args.command == "financial":
            print(json.dumps(build_financial_allocations(session, args.snapshot), indent=2, default=str))
        elif args.command == "accounting":
            print(json.dumps(build_accounting_snapshot(session, args.snapshot), indent=2, default=str))
        elif args.command == "blueprint":
            print(json.dumps(build_blueprints(session, args.snapshot), indent=2, default=str))
        elif args.command == "foundation":
            print(json.dumps(build_erp_foundation(session, args.snapshot), indent=2, default=str))
        elif args.command == "masters":
            print(json.dumps(build_canonical_masters(session, args.snapshot), indent=2, default=str))
        elif args.command == "transactions":
            print(json.dumps(build_canonical_transactions(session, args.snapshot), indent=2, default=str))
        elif args.command == "ledger":
            print(json.dumps(build_canonical_ledger(session, args.snapshot), indent=2, default=str))
        elif args.command == "security":
            print(json.dumps(build_security_controls(session, args.snapshot), indent=2, default=str))
        elif args.command == "coverage":
            print(json.dumps(build_coverage_closure(session, args.snapshot), indent=2, default=str))
        elif args.command == "residuals":
            print(json.dumps(build_residual_workflows(session, args.snapshot), indent=2, default=str))
        elif args.command == "runtime":
            print(json.dumps(build_runtime_foundation(session, args.snapshot), indent=2, default=str))


if __name__ == "__main__":
    main()
