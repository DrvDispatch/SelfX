"""Transactional PostgreSQL schema revisions.

The first revision adopts the schema used by earlier SelfX versions and fills in
missing tables. Later revisions should make explicit changes to existing tables.
"""

import logging

from sqlalchemy import Column, DateTime, MetaData, String, Table, func, select, text
from sqlalchemy.engine import Connection, Engine

from .db import Base, engine

logger = logging.getLogger(__name__)

_SCHEMA_LOCK = 0x53656C66584442  # SelfXDB
_schema_revisions = Table(
    "selfx_schema_revisions",
    MetaData(),
    Column("revision", String(80), primary_key=True),
    Column("applied_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


def _initial_schema(conn: Connection) -> None:
    from . import models  # noqa: F401
    from .kb import models as kb_models  # noqa: F401
    from .kb.schema import ensure_search_indexes

    if not conn.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")):
        conn.execute(text("CREATE EXTENSION vector"))
    Base.metadata.create_all(bind=conn)
    ensure_search_indexes(conn)


_REVISIONS = (("0001_initial", _initial_schema),)


def apply_migrations(db_engine: Engine) -> None:
    applied = []
    with db_engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SCHEMA_LOCK})
        _schema_revisions.create(bind=conn, checkfirst=True)
        installed = set(conn.scalars(select(_schema_revisions.c.revision)))
        for revision, migrate in _REVISIONS:
            if revision in installed:
                continue
            migrate(conn)
            conn.execute(_schema_revisions.insert().values(revision=revision))
            applied.append(revision)

    for revision in applied:
        logger.info("Applied database revision %s", revision)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    apply_migrations(engine)
