from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import (
    StgCoaAccount,
    StgInventoryOpeningControl,
    StgJournalBlueprint,
    StgJournalBlueprintLine,
)


def clear_blueprint_outputs(session: Session, snapshot_id: int) -> None:
    journal_ids = select(StgJournalBlueprint.id).where(StgJournalBlueprint.snapshot_id == snapshot_id)
    session.execute(delete(StgJournalBlueprintLine).where(StgJournalBlueprintLine.journal_id.in_(journal_ids)))
    session.execute(delete(StgJournalBlueprint).where(StgJournalBlueprint.snapshot_id == snapshot_id))
    session.execute(delete(StgInventoryOpeningControl).where(StgInventoryOpeningControl.snapshot_id == snapshot_id))
    session.execute(delete(StgCoaAccount).where(StgCoaAccount.snapshot_id == snapshot_id))
