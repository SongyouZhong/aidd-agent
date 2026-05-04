"""Pathway / Drug / DiseaseAssociation / Paper ORM + M2M tables.

Kept in a single module to avoid mass file proliferation while still
matching the logical grouping in the design plan.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.target import Target

# --- Many-to-many association tables ---------------------------------

target_pathway = Table(
    "target_pathway",
    Base.metadata,
    Column("target_id", UUID(as_uuid=True), ForeignKey("targets.id", ondelete="CASCADE"), primary_key=True),
    Column("pathway_id", UUID(as_uuid=True), ForeignKey("pathways.id", ondelete="CASCADE"), primary_key=True),
)

target_paper = Table(
    "target_paper",
    Base.metadata,
    Column("target_id", UUID(as_uuid=True), ForeignKey("targets.id", ondelete="CASCADE"), primary_key=True),
    Column("paper_id", UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True),
)


# --- Pathway ---------------------------------------------------------


class Pathway(Base):
    __tablename__ = "pathways"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_pathway_src_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    targets: Mapped[list[Target]] = relationship(secondary=target_pathway, backref="pathways")


# --- Drug + activity binding -----------------------------------------


class Drug(Base):
    __tablename__ = "drugs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chembl_id: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    modality: Mapped[str] = mapped_column(String(32), nullable=False, default="small_molecule")
    smiles: Mapped[str | None] = mapped_column(Text, nullable=True)
    inchikey: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    peptide_sequence: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_phase: Mapped[float | None] = mapped_column(Float, nullable=True)
    mechanism_of_action: Mapped[str | None] = mapped_column(Text, nullable=True)


class TargetDrugActivity(Base):
    __tablename__ = "target_drug_activities"
    __table_args__ = (
        UniqueConstraint(
            "target_id", "drug_id", "activity_type", name="uq_tda_target_drug_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("targets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    drug_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drugs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    activity_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    value_nm: Mapped[float | None] = mapped_column(Float, nullable=True)
    pchembl: Mapped[float | None] = mapped_column(Float, nullable=True)
    assay_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)


# --- DiseaseAssociation ---------------------------------------------


class DiseaseAssociation(Base):
    __tablename__ = "disease_associations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("targets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    disease_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    disease_name: Mapped[str] = mapped_column(String(255), nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)


# --- Paper -----------------------------------------------------------


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pmid: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True, index=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    journal: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    targets: Mapped[list[Target]] = relationship(secondary=target_paper, backref="papers")
