"""daily_digests.body_md — сохраняем тело дайджеста для диагностики

Revision ID: 20260509_0420_e7f9a1c3b5d7
Revises: 20260508_1300_d4e6f8a0c2b4
Create Date: 2026-05-09 04:20:00.000000

TECH-010 (observability). До сих пор daily_digests хранил только
метаданные (date, sent_at, chat_count, message_count). Это блокировало
диагностику качества дайджестов: нельзя было увидеть, что именно ушло
владельцу. Добавляем nullable колонку body_md, в которую DigestService
будет писать рендеренный MarkdownV2-текст перед отправкой. Старые
строки остаются с body_md=NULL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260509_0420_e7f9a1c3b5d7"
down_revision: Union[str, None] = "20260508_1300_d4e6f8a0c2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "daily_digests",
        sa.Column("body_md", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("daily_digests", "body_md")
