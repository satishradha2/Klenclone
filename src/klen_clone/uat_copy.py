from __future__ import annotations

from pathlib import Path
import shutil

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from .auth import hash_password
from .db import make_engine
from .models import (
    ErpAuthPrincipal,
    ErpLocation,
    ErpSecurityLocationScope,
    ErpSecurityPermission,
    ErpSecurityRole,
    ErpSecurityRolePermission,
    ErpSecurityUser,
    ErpSecurityUserRole,
    RawFileManifest,
    RawRecord,
    SourceSnapshot,
)


UAT_PERMISSIONS = (
    "customer.view",
    "supplier.view",
    "product.view",
    "sell.view",
    "purchase.view",
    "stock_report.view",
    "accounting.view_reports",
)


def prepare_uat_copy(source_url: str, destination_url: str, snapshot_name: str,
                     password: str, login_name: str = "synthetic.uat.reader") -> dict:
    source = make_url(source_url)
    destination = make_url(destination_url)
    if source.drivername != "sqlite" or destination.drivername != "sqlite":
        raise ValueError("UAT copy preparation requires explicit SQLite source and destination URLs")
    source_path = Path(source.database or "").resolve()
    destination_path = Path(destination.database or "").resolve()
    if source_path == destination_path:
        raise ValueError("UAT destination must be different from the source clone")
    if not source_path.is_file():
        raise FileNotFoundError(f"Source clone not found: {source_path}")
    if destination_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing UAT copy: {destination_path}")
    if len(password) < 12:
        raise ValueError("Synthetic UAT password must contain at least 12 characters")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)
    engine = make_engine(destination_url)
    with Session(engine) as session:
        snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
        if not snapshot:
            raise ValueError("Configured snapshot is not present in the copied database")
        if session.scalar(select(ErpAuthPrincipal.id).where(
                ErpAuthPrincipal.snapshot_id == snapshot.id,
                ErpAuthPrincipal.login_name == login_name)):
            raise ValueError("Synthetic UAT principal already exists")
        location = session.scalar(select(ErpLocation).where(
            ErpLocation.snapshot_id == snapshot.id).order_by(ErpLocation.id))
        if not location:
            raise ValueError("UAT requires at least one cloned location")

        manifest = RawFileManifest(
            snapshot_id=snapshot.id,
            relative_path="synthetic-uat/principal.json",
            entity_type="synthetic_uat_principal",
            sha256="0" * 64,
            byte_length=0,
            media_type="application/json",
            source_record_count=1,
        )
        session.add(manifest)
        session.flush()
        raw = RawRecord(manifest_id=manifest.id, ordinal=1, source_record_id=login_name,
                        payload={"synthetic_uat": True, "source_data": False})
        role = ErpSecurityRole(snapshot_id=snapshot.id, role_code="synthetic_uat_reader",
                               role_name="Synthetic UAT Reader", migration_status="validation_only",
                               assignment_enabled=True, evidence={"synthetic_uat": True})
        session.add_all([raw, role])
        session.flush()
        user = ErpSecurityUser(
            snapshot_id=snapshot.id,
            source_user_id=raw.id,
            username=login_name,
            display_name="Synthetic UAT Reader",
            source_role_name="synthetic_uat_reader",
            account_status="validation_only",
            password_material_copied=False,
            authentication_enabled=True,
            evidence={"synthetic_uat": True, "migrated_identity": False},
        )
        session.add(user)
        session.flush()
        principal = ErpAuthPrincipal(
            snapshot_id=snapshot.id,
            security_user_id=user.id,
            login_name=login_name,
            password_hash=hash_password(password),
            auth_status="active",
            mfa_enrolled=False,
            authentication_enabled=True,
            evidence={"synthetic_uat": True, "password_material_copied": False},
        )
        session.add_all([
            principal,
            ErpSecurityUserRole(user_id=user.id, role_id=role.id, source_observed=False,
                                assignment_enabled=True),
            ErpSecurityLocationScope(snapshot_id=snapshot.id, user_id=user.id,
                                     location_id=location.id, scope_mode="explicit",
                                     access_enabled=True, evidence={"synthetic_uat": True}),
        ])
        permissions = list(session.scalars(select(ErpSecurityPermission).where(
            ErpSecurityPermission.snapshot_id == snapshot.id,
            ErpSecurityPermission.permission_code.in_(UAT_PERMISSIONS))).all())
        missing = sorted(set(UAT_PERMISSIONS) - {item.permission_code for item in permissions})
        if missing:
            raise ValueError(f"Required cloned permission definitions are missing: {', '.join(missing)}")
        for permission in permissions:
            permission.grant_enabled = True
            permission.mode = "read_uat"
            session.add(ErpSecurityRolePermission(
                role_id=role.id, permission_id=permission.id,
                source_granted=False, target_granted=True,
                exclusion_reason="Synthetic UAT reader only; not a production grant."))
        session.commit()
        return {"status": "prepared", "database": str(destination_path),
                "snapshot": snapshot.name, "login_name": login_name,
                "location_code": location.code, "permissions": list(UAT_PERMISSIONS),
                "source_clone_modified": False, "posting_enabled": False}
