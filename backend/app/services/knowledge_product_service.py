# backend/app/services/knowledge_product_service.py
import json
import logging
import re

from sqlalchemy.orm import Session

from app.models.knowledge_product import KnowledgeProduct

logger = logging.getLogger(__name__)

# Stopwords: common Vietnamese filler words and noise in product names
_STOPWORDS = frozenset({
    # Vietnamese with diacritics
    "cho", "và", "của", "các", "với", "có", "được", "từ", "trong", "không",
    "đến", "một", "như", "là", "này", "theo", "về", "hay", "hoặc", "nhiều",
    "mới", "đẹp", "tốt", "rẻ", "giá", "bán", "mua", "hàng", "sản", "phẩm",
    "chất", "lượng", "cao", "cấp", "siêu", "hot", "sale", "flash",
    "dành", "riêng", "loại", "kiểu", "dùng", "chính", "hãng", "hiệu",
    "miếng", "cái", "bộ", "set", "chiếc", "đôi", "combo",
    # Vietnamese without diacritics (user input often lacks diacritics)
    "va", "cua", "cac", "voi", "duoc", "tu", "khong", "den", "mot",
    "nhu", "nay", "ve", "nhieu", "moi", "dep", "tot", "re",
    "danh", "rieng", "loai", "kieu", "dung", "chinh", "hang", "hieu",
    "mieng", "bo", "chiec", "doi",
    # English common
    "the", "for", "and", "with", "size", "new", "top", "best", "pro",
})


class KnowledgeProductService:
    def __init__(self, db: Session) -> None:
        self._db = db

    # --- Parsing ---

    def parse_shopee_cart_json(self, raw_json: str) -> list[dict]:
        """Parse raw Shopee cart/product API JSON into a list of product dicts.

        Handles the format: { "data": { "items": [...] } }
        """
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            raise ValueError("JSON không hợp lệ")

        items = []
        if isinstance(data, dict):
            if "data" in data and isinstance(data["data"], dict):
                items = data["data"].get("items", [])
            elif "items" in data:
                items = data["items"]
            elif isinstance(data.get("data"), list):
                items = data["data"]
        elif isinstance(data, list):
            items = data

        products = []
        for item in items:
            # Extract rating from popularity_labels
            rating_value = None
            rating_count = None
            sold_count = item.get("sold")
            labels = item.get("label", {})
            for pl in labels.get("popularity_labels", []):
                if pl.get("type_name") == "rating_star":
                    try:
                        rating_value = float(pl.get("rating_star_value", 0))
                    except (ValueError, TypeError):
                        pass
                elif pl.get("type_name") == "star_rate":
                    rating_count = pl.get("star_count")
                elif pl.get("type_name") == "sold_cnt" and not sold_count:
                    sold_count = pl.get("sold")

            # Extract voucher info summary
            voucher_summaries = []
            for vl in labels.get("voucher_label", []):
                code = vl.get("voucher_code", "")
                pct = vl.get("discount_percentage", 0)
                if pct:
                    voucher_summaries.append(f"{code}: giam {pct}%")
                elif "FSV" in code:
                    voucher_summaries.append("Freeship")
                elif code:
                    voucher_summaries.append(code)

            # Extract promotion info
            promo_list = []
            item_promo = item.get("item_promotion", {})
            for dp in item_promo.get("display_promotions", []):
                promo_type = dp.get("promotion_type", 0)
                if promo_type:
                    promo_list.append({
                        "type": promo_type,
                        "stock": dp.get("stock", 0),
                        "start_time": dp.get("start_time", 0),
                        "end_time": dp.get("end_time", 0),
                    })

            # Parse prices (Shopee sometimes returns as string)
            price_min = _safe_int(item.get("price_min") or item.get("price"))
            price_max = _safe_int(item.get("price_max") or item.get("price"))
            discount = item.get("discount") or 0

            stock_qty = item.get("display_total_stock") or item.get("normal_stock") or 0
            is_oos = item.get("is_oos", False)

            products.append({
                "product_order": item.get("id", 0),
                "item_id": item.get("item_id", 0),
                "shop_id": item.get("shop_id", 0),
                "name": item.get("name", ""),
                "price_min": price_min,
                "price_max": price_max,
                "discount_pct": discount,
                "in_stock": not is_oos and stock_qty > 0,
                "stock_qty": stock_qty,
                "sold": sold_count,
                "rating": rating_value,
                "rating_count": rating_count,
                "voucher_info": json.dumps(voucher_summaries, ensure_ascii=False) if voucher_summaries else None,
                "promotion_info": json.dumps(promo_list, ensure_ascii=False) if promo_list else None,
            })

        return products

    # --- Keyword extraction (code-based, no AI needed) ---

    @staticmethod
    def extract_keywords(product_name: str) -> list[str]:
        """Extract keywords from a product name using simple text processing.

        Strategy:
        1. Remove noise characters and normalize
        2. Split into tokens
        3. Filter stopwords and short tokens
        4. Build bigrams for meaningful compound terms
        5. Return unique keywords
        """
        # Normalize: lowercase, remove special chars but keep Vietnamese diacritics
        name = product_name.lower().strip()
        # Remove size/spec patterns like "39-80kg", "12+4", "210x222"
        name = re.sub(r"\d+[\-x×]\d+(\w+)?", "", name)
        # Remove standalone numbers
        name = re.sub(r"\b\d+\b", "", name)
        # Remove noise punctuation but keep letters (including Vietnamese)
        name = re.sub(r"[^\w\s]", " ", name)
        # Collapse whitespace
        name = re.sub(r"\s+", " ", name).strip()

        tokens = name.split()
        # Filter stopwords and very short tokens (1 char)
        meaningful = [t for t in tokens if t not in _STOPWORDS and len(t) > 1]

        keywords: list[str] = []
        seen: set[str] = set()

        # Add individual meaningful tokens
        for token in meaningful:
            if token not in seen:
                keywords.append(token)
                seen.add(token)

        # Build bigrams for compound terms (e.g., "áo thun", "ốp lưng")
        for i in range(len(meaningful) - 1):
            bigram = f"{meaningful[i]} {meaningful[i + 1]}"
            if bigram not in seen:
                keywords.append(bigram)
                seen.add(bigram)

        # Limit to top keywords (unigrams first, then bigrams)
        return keywords[:10]

    def extract_keywords_batch(self, product_names: list[str]) -> list[list[str]]:
        """Extract keywords for multiple products."""
        return [self.extract_keywords(name) for name in product_names]

    # --- Import pipeline ---

    def import_products(
        self, nick_live_id: int, raw_json: str
    ) -> list[KnowledgeProduct]:
        """Full pipeline: parse JSON -> extract keywords (code-based) -> save to DB."""
        parsed = self.parse_shopee_cart_json(raw_json)
        if not parsed:
            return []

        # Batch extract keywords (no AI, pure code)
        names = [p["name"] for p in parsed]
        all_keywords = self.extract_keywords_batch(names)

        # Delete existing products for this nick
        self.delete_products(nick_live_id)

        # Insert new products
        products = []
        for i, p_data in enumerate(parsed):
            keywords = all_keywords[i] if i < len(all_keywords) else []
            product = KnowledgeProduct(
                product_order=p_data["product_order"],
                nick_live_id=nick_live_id,
                item_id=p_data["item_id"],
                shop_id=p_data["shop_id"],
                name=p_data["name"],
                keywords=json.dumps(keywords, ensure_ascii=False),
                price_min=p_data["price_min"],
                price_max=p_data["price_max"],
                discount_pct=p_data["discount_pct"],
                in_stock=p_data["in_stock"],
                stock_qty=p_data["stock_qty"],
                sold=p_data["sold"],
                rating=p_data["rating"],
                rating_count=p_data["rating_count"],
                voucher_info=p_data["voucher_info"],
                promotion_info=p_data["promotion_info"],
            )
            self._db.add(product)
            products.append(product)

        self._db.commit()
        for p in products:
            self._db.refresh(p)

        return products

    # --- CRUD ---

    def get_products(self, nick_live_id: int) -> list[KnowledgeProduct]:
        return (
            self._db.query(KnowledgeProduct)
            .filter(KnowledgeProduct.nick_live_id == nick_live_id)
            .order_by(KnowledgeProduct.product_order)
            .all()
        )

    def find_product_by_order(self, nick_live_id: int, order: int) -> KnowledgeProduct | None:
        return (
            self._db.query(KnowledgeProduct)
            .filter(
                KnowledgeProduct.nick_live_id == nick_live_id,
                KnowledgeProduct.product_order == order,
            )
            .first()
        )

    def find_products_by_keyword(self, nick_live_id: int, keyword: str) -> list[KnowledgeProduct]:
        """Search products whose keywords contain the given keyword (case-insensitive)."""
        kw_lower = keyword.lower()
        products = self.get_products(nick_live_id)
        matched = []
        for p in products:
            try:
                kws = json.loads(p.keywords)
                if any(kw_lower in k.lower() for k in kws):
                    matched.append(p)
            except (json.JSONDecodeError, TypeError):
                continue
        return matched

    def delete_products(self, nick_live_id: int) -> int:
        count = (
            self._db.query(KnowledgeProduct)
            .filter(KnowledgeProduct.nick_live_id == nick_live_id)
            .delete()
        )
        self._db.commit()
        return count


def _safe_int(value: str | int | None) -> int | None:
    """Safely convert a value to int."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
