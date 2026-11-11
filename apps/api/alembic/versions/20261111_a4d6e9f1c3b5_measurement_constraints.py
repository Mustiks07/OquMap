"""measurement constraints

Revision ID: a4d6e9f1c3b5
Revises: f3c5d8e2a7b1
Create Date: 2026-11-11 14:25:44.897095

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a4d6e9f1c3b5'
down_revision: str | Sequence[str] | None = 'f3c5d8e2a7b1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TARGET_CHECK = (
    "(target_type = 'topic' AND topic_id IS NOT NULL AND objective_id IS NULL AND misconception_code IS NULL) OR "
    "(target_type = 'objective' AND objective_id IS NOT NULL AND topic_id IS NULL AND misconception_code IS NULL) OR "
    "(target_type = 'misconception' AND misconception_code IS NOT NULL AND topic_id IS NULL AND objective_id IS NULL)")
DOSAGE = "minutes_per_session > 0 AND sessions_per_week > 0 AND duration_weeks > 0"
COUNTS = ("activities_planned >= 0 AND activities_completed >= 0 AND (learners_present IS NULL OR learners_present >= 0) "
          "AND (learners_assigned IS NULL OR learners_assigned >= 0)")


def upgrade() -> None:
    """Integrity constraints: positive dosage, non-negative counts, one field per target type, one correction per
    fidelity log, conclusion/outcome of the same pilot and org, pilot/evidence version of the selected intervention,
    unique decision version within a group. Unique constraints are created before the composite FKs using them."""
    with op.batch_alter_table('intervention_versions', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_intervention_versions_id_intervention', ['id', 'intervention_id'])
        batch_op.create_check_constraint('ck_intervention_versions_dosage', DOSAGE)
    with op.batch_alter_table('pilot_outcomes', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_pilot_outcomes_id_pilot_org', ['id', 'pilot_id', 'org_id'])
    with op.batch_alter_table('intervention_targets', schema=None) as batch_op:
        batch_op.create_check_constraint('ck_intervention_targets_one_field', TARGET_CHECK)
    with op.batch_alter_table('fidelity_logs', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_fidelity_logs_single_correction', ['corrects_log_id'])
        batch_op.create_check_constraint('ck_fidelity_logs_counts', COUNTS)
    with op.batch_alter_table('pilots', schema=None) as batch_op:
        batch_op.create_foreign_key('fk_pilots_version_of_intervention', 'intervention_versions',
                                    ['intervention_version_id', 'intervention_id'], ['id', 'intervention_id'])
        batch_op.create_check_constraint('ck_pilots_dosage', DOSAGE)
    with op.batch_alter_table('intervention_evidence', schema=None) as batch_op:
        batch_op.create_foreign_key('fk_intervention_evidence_version_of_intervention', 'intervention_versions',
                                    ['intervention_version_id', 'intervention_id'], ['id', 'intervention_id'])
    with op.batch_alter_table('pilot_conclusions', schema=None) as batch_op:
        batch_op.create_foreign_key('fk_pilot_conclusions_outcome_same_pilot', 'pilot_outcomes',
                                    ['outcome_id', 'pilot_id', 'org_id'], ['id', 'pilot_id', 'org_id'])
    with op.batch_alter_table('decisions', schema=None) as batch_op:
        batch_op.create_index('uq_decisions_group_version', ['decision_group_id', 'version'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('decisions', schema=None) as batch_op:
        batch_op.drop_index('uq_decisions_group_version')
    with op.batch_alter_table('pilot_conclusions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_pilot_conclusions_outcome_same_pilot', type_='foreignkey')
    with op.batch_alter_table('intervention_evidence', schema=None) as batch_op:
        batch_op.drop_constraint('fk_intervention_evidence_version_of_intervention', type_='foreignkey')
    with op.batch_alter_table('pilots', schema=None) as batch_op:
        batch_op.drop_constraint('ck_pilots_dosage', type_='check')
        batch_op.drop_constraint('fk_pilots_version_of_intervention', type_='foreignkey')
    with op.batch_alter_table('fidelity_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_fidelity_logs_counts', type_='check')
        batch_op.drop_constraint('uq_fidelity_logs_single_correction', type_='unique')
    with op.batch_alter_table('intervention_targets', schema=None) as batch_op:
        batch_op.drop_constraint('ck_intervention_targets_one_field', type_='check')
    with op.batch_alter_table('pilot_outcomes', schema=None) as batch_op:
        batch_op.drop_constraint('uq_pilot_outcomes_id_pilot_org', type_='unique')
    with op.batch_alter_table('intervention_versions', schema=None) as batch_op:
        batch_op.drop_constraint('ck_intervention_versions_dosage', type_='check')
        batch_op.drop_constraint('uq_intervention_versions_id_intervention', type_='unique')
