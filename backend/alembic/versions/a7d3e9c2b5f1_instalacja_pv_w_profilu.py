"""Instalacja PV (ZP-148) i lokalizacja domu (ZP-116) w profilu.

Moc net-meteringu staje się jedną grupą paneli na południe z nachyleniem 35°. Lokalizacja (base_info.location)
nie wymaga migracji: backend wyznacza ją przy pierwszym odczycie albo zapisie profilu.

Revision ID: a7d3e9c2b5f1
Revises: f2c7a9d4e1b8
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a7d3e9c2b5f1"
down_revision: Union[str, Sequence[str], None] = "f2c7a9d4e1b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UPGRADE_NET_METERING = """
    UPDATE user_profiles
    SET pv_config = pv_config || jsonb_build_object(
        'installation',
        jsonb_build_object(
            'arrays', jsonb_build_array(jsonb_build_object(
                'power_kwp', (pv_config->>'power_of_pv_kwp')::float,
                'azimuth', 0,
                'tilt', 35,
                'panel_count', NULL
            )),
            'panel_power_w', NULL,
            'inverter_power_kw', NULL,
            'estimated', false,
            'total_kwp', (pv_config->>'power_of_pv_kwp')::float
        )
    )
    WHERE pv_config->>'mode' = 'net_metering'
      AND pv_config ? 'power_of_pv_kwp'
      AND NOT pv_config ? 'installation'
"""

DOWNGRADE_STATEMENTS = (
    """
    UPDATE user_profiles
    SET pv_config = (pv_config - 'installation')
        || jsonb_build_object('power_of_pv_kwp', (pv_config->'installation'->>'total_kwp')::float)
    WHERE pv_config->>'mode' = 'net_metering' AND pv_config ? 'installation'
    """,
    "UPDATE user_profiles SET pv_config = pv_config - 'installation' WHERE pv_config ? 'installation'",
    "UPDATE user_profiles SET base_info = base_info - 'location' WHERE base_info ? 'location'",
)


def upgrade() -> None:
    op.execute(UPGRADE_NET_METERING)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
