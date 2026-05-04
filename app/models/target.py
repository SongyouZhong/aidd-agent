"""Target / Protein ORM models for the Target-Discovery feature."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.target_report import TargetReport


class Target(Base):
    __tablename__ = "targets"
    __table_args__ = (
        UniqueConstraint("name", "organism", name="uq_target_name_organism"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    gene_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    organism: Mapped[str] = mapped_column(String(128), nullable=False, default="Homo sapiens")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    uniprot_ids: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    proteins: Mapped[list["ProteinRecord"]] = relationship(
        back_populates="target", cascade="all, delete-orphan"
    )
    reports: Mapped[list["TargetReport"]] = relationship(
        back_populates="target", cascade="all, delete-orphan"
    )


class ProteinRecord(Base):
    __tablename__ = "proteins"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("targets.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    uniprot_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gene: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sequence_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sequence: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdb_ids: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    alphafold_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    interpro_domains: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    target: Mapped[Target] = relationship(back_populates="proteins")
