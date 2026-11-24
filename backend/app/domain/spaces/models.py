from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Space(Base):
    __tablename__ = "spaces"
    __table_args__ = (
        # no máximo um espaço family por dono (v1)
        Index(
            "uq_spaces_one_family_per_owner", "owner_id", unique=True,
            postgresql_where=text("type = 'family'"),
        ),
    )  # fmt: skip

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    type: Mapped[str] = mapped_column(String(16))  # personal | family
    name: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SpaceMember(Base):
    __tablename__ = "space_members"

    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(16))  # owner | member
    default_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"))


class SpaceInvite(Base):
    __tablename__ = "space_invites"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"))
    token: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
