# backend/app/models/knowledge_product.py
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KnowledgeProduct(Base):
    __tablename__ = "knowledge_products"
    __table_args__ = (
        UniqueConstraint("nick_live_id", "product_order", name="uq_nick_product_order"),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_order: Mapped[int] = mapped_column(Integer, nullable=False)
    nick_live_id: Mapped[int] = mapped_column(Integer, nullable=False)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    price_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    in_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stock_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    voucher_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    promotion_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
