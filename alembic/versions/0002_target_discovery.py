"""target discovery models

Revision ID: 0002_target_discovery
Revises: 0001_init
Create Date: 2026-05-04

"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0002_target_discovery"
down_revision: Union[str, Sequence[str], None] = "0001_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- targets -----------------------------------------------------
    op.create_table(
        "targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("gene_symbol", sa.String(length=64), nullable=True),
        sa.Column("organism", sa.String(length=128), nullable=False, server_default="Homo sapiens"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "uniprot_ids",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", "organism", name="uq_target_name_organism"),
    )
    op.create_index("ix_targets_name", "targets", ["name"])
    op.create_index("ix_targets_gene_symbol", "targets", ["gene_symbol"])

    # --- proteins ----------------------------------------------------
    op.create_table(
        "proteins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("uniprot_id", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("gene", sa.String(length=64), nullable=True),
        sa.Column("sequence_length", sa.Integer(), nullable=True),
        sa.Column("sequence", sa.Text(), nullable=True),
        sa.Column("pdb_ids", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("alphafold_id", sa.String(length=32), nullable=True),
        sa.Column(
            "interpro_domains",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_index("ix_proteins_target_id", "proteins", ["target_id"])
    op.create_index("ix_proteins_uniprot_id", "proteins", ["uniprot_id"])

    # --- pathways ----------------------------------------------------
    op.create_table(
        "pathways",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=512), nullable=True),
        sa.UniqueConstraint("source", "external_id", name="uq_pathway_src_id"),
    )

    op.create_table(
        "target_pathway",
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "pathway_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pathways.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # --- drugs -------------------------------------------------------
    op.create_table(
        "drugs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("chembl_id", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("modality", sa.String(length=32), nullable=False, server_default="small_molecule"),
        sa.Column("smiles", sa.Text(), nullable=True),
        sa.Column("inchikey", sa.String(length=32), nullable=True),
        sa.Column("peptide_sequence", sa.Text(), nullable=True),
        sa.Column("max_phase", sa.Float(), nullable=True),
        sa.Column("mechanism_of_action", sa.Text(), nullable=True),
        sa.UniqueConstraint("chembl_id", name="uq_drugs_chembl_id"),
    )
    op.create_index("ix_drugs_chembl_id", "drugs", ["chembl_id"])
    op.create_index("ix_drugs_inchikey", "drugs", ["inchikey"])

    op.create_table(
        "target_drug_activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "drug_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drugs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("activity_type", sa.String(length=16), nullable=True),
        sa.Column("value_nm", sa.Float(), nullable=True),
        sa.Column("pchembl", sa.Float(), nullable=True),
        sa.Column("assay_description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.UniqueConstraint(
            "target_id", "drug_id", "activity_type", name="uq_tda_target_drug_type"
        ),
    )
    op.create_index("ix_tda_target_id", "target_drug_activities", ["target_id"])
    op.create_index("ix_tda_drug_id", "target_drug_activities", ["drug_id"])

    # --- disease associations ---------------------------------------
    op.create_table(
        "disease_associations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("disease_id", sa.String(length=64), nullable=False),
        sa.Column("disease_name", sa.String(length=255), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("evidence_summary", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=512), nullable=True),
    )
    op.create_index("ix_disease_assoc_target_id", "disease_associations", ["target_id"])
    op.create_index("ix_disease_assoc_disease_id", "disease_associations", ["disease_id"])

    # --- papers -----------------------------------------------------
    op.create_table(
        "papers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("pmid", sa.String(length=32), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("journal", sa.String(length=255), nullable=True),
        sa.Column("url", sa.String(length=512), nullable=True),
        sa.Column("extra", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("pmid", name="uq_papers_pmid"),
    )
    op.create_index("ix_papers_pmid", "papers", ["pmid"])
    op.create_index("ix_papers_doi", "papers", ["doi"])

    op.create_table(
        "target_paper",
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # --- target_reports --------------------------------------------
    op.create_table(
        "target_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("notes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_target_reports_target_id", "target_reports", ["target_id"])
    op.create_index("ix_target_reports_session_id", "target_reports", ["session_id"])
    op.create_index("ix_target_reports_user_id", "target_reports", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_target_reports_user_id", table_name="target_reports")
    op.drop_index("ix_target_reports_session_id", table_name="target_reports")
    op.drop_index("ix_target_reports_target_id", table_name="target_reports")
    op.drop_table("target_reports")

    op.drop_table("target_paper")
    op.drop_index("ix_papers_doi", table_name="papers")
    op.drop_index("ix_papers_pmid", table_name="papers")
    op.drop_table("papers")

    op.drop_index("ix_disease_assoc_disease_id", table_name="disease_associations")
    op.drop_index("ix_disease_assoc_target_id", table_name="disease_associations")
    op.drop_table("disease_associations")

    op.drop_index("ix_tda_drug_id", table_name="target_drug_activities")
    op.drop_index("ix_tda_target_id", table_name="target_drug_activities")
    op.drop_table("target_drug_activities")

    op.drop_index("ix_drugs_inchikey", table_name="drugs")
    op.drop_index("ix_drugs_chembl_id", table_name="drugs")
    op.drop_table("drugs")

    op.drop_table("target_pathway")
    op.drop_table("pathways")

    op.drop_index("ix_proteins_uniprot_id", table_name="proteins")
    op.drop_index("ix_proteins_target_id", table_name="proteins")
    op.drop_table("proteins")

    op.drop_index("ix_targets_gene_symbol", table_name="targets")
    op.drop_index("ix_targets_name", table_name="targets")
    op.drop_table("targets")
