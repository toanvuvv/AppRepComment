from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NickLive(Base):
    __tablename__ = "nick_lives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shop_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cookies: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
