from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Goal(Base):
    __tablename__ = "goals"
    __table_args__ = (CheckConstraint("target_cents > 0", name="ck_goals_target_positive"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    target_cents: Mapped[int] = mapped_column(BigInteger)
    deadline: Mapped[date | None] = mapped_column(Date)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"))  # informativo
    created_on: Mapped[date] = mapped_column(Date)  # dia local de criação: base do ritmo linear
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
