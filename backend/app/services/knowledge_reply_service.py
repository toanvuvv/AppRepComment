# backend/app/services/knowledge_reply_service.py
import json
import logging
import math
import re
import unicodedata

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

INTENT_CATEGORIES = {
    "product_consult": "tu van/hoi chi tiet san pham",
    "stock_inquiry": "hoi con hang, con variant khong",
    "price_inquiry": "hoi gia, voucher, giam gia",
    "purchase_intent": "muon mua, chot don",
    "positive_review": "khen ngoi, hai long",
    "complaint": "khieu nai",
    "other": "chao hoi, khong lien quan",
}

# Regex patterns for product reference extraction
_PATTERNS_WITH_PREFIX = [
    re.compile(r"(?:số|so|sp|sản phẩm|san pham|mã|ma|#)\s*(\d+)", re.IGNORECASE),
]
_PATTERN_BARE_NUMBER = re.compile(r"\b(\d{1,3})\s*(?:ạ|a|nha|nhé|nhe|đi|di|ơi|oi|luôn|luon)\b", re.IGNORECASE)


def _remove_diacritics(text: str) -> str:
    """Remove Vietnamese diacritics: 'vỏ điện thoại' -> 'vo dien thoai'."""
    # Normalize to decomposed form, strip combining marks
    nfkd = unicodedata.normalize("NFKD", text)
    result = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Handle special Vietnamese chars not covered by NFKD
    result = result.replace("đ", "d").replace("Đ", "D")
    return result


def _build_idf(keyword_index: dict[int, list[str]]) -> dict[str, float]:
    """Compute IDF weight for each keyword across all products.

    Keywords unique to 1 product get high weight; common ones get low weight.
    """
    total_products = len(keyword_index)
    if total_products == 0:
        return {}

    # Count how many products each keyword appears in
    kw_doc_count: dict[str, int] = {}
    for keywords in keyword_index.values():
        seen: set[str] = set()
        for kw in keywords:
            normalized = _remove_diacritics(kw.lower())
            if normalized not in seen:
                kw_doc_count[normalized] = kw_doc_count.get(normalized, 0) + 1
                seen.add(normalized)

    # IDF = log(total_products / doc_count) + 1
    return {
        kw: math.log(total_products / count) + 1
        for kw, count in kw_doc_count.items()
    }


def _word_boundary_match(keyword: str, words: set[str], text_normalized: str) -> bool:
    """Match keyword against text with word boundary awareness.

    Single-word keywords match against word set (exact word match).
    Multi-word keywords match as substring (phrase match).
    """
    if " " in keyword:
        return keyword in text_normalized
    return keyword in words


def extract_product_reference(
    comment_text: str,
    keyword_index: dict[int, list[str]],
) -> int | None:
    """Extract product order number from a comment.

    Uses 3 strategies in priority order:
    1. Explicit number reference ("sp 3", "#3")
    2. Bare number with Vietnamese particles ("3 a", "3 nha")
    3. Keyword scoring with IDF weighting + diacritics normalization
    """
    text = comment_text.strip().lower()

    # Pattern 1: Explicit prefix patterns ("so 3", "#3", "sp 3")
    for pattern in _PATTERNS_WITH_PREFIX:
        match = pattern.search(text)
        if match:
            num = int(match.group(1))
            if num in keyword_index:
                return num

    # Pattern 2: Bare number with Vietnamese particles ("3 a", "3 nha")
    match = _PATTERN_BARE_NUMBER.search(text)
    if match:
        num = int(match.group(1))
        if num in keyword_index:
            return num

    # Pattern 3: Keyword scoring with IDF + diacritics normalization
    idf = _build_idf(keyword_index)

    # Normalize comment text (both with and without diacritics)
    text_with_diacritics = text
    text_no_diacritics = _remove_diacritics(text)
    words_with = set(text_with_diacritics.split())
    words_no = set(text_no_diacritics.split())

    best_match_order = None
    best_score = 0.0
    best_match_count = 0

    for order, keywords in keyword_index.items():
        score = 0.0
        match_count = 0

        for kw in keywords:
            kw_lower = kw.lower()
            kw_normalized = _remove_diacritics(kw_lower)
            if len(kw_normalized) < 2:
                continue

            # Try exact match first, then diacritics-stripped match
            matched = (
                _word_boundary_match(kw_lower, words_with, text_with_diacritics)
                or _word_boundary_match(kw_normalized, words_no, text_no_diacritics)
            )

            if matched:
                weight = idf.get(kw_normalized, 1.0)
                score += len(kw_normalized) * weight
                match_count += 1

        # Require at least 2 keyword matches to reduce false positives
        if match_count >= 2 and score > best_score:
            best_score = score
            best_match_order = order
            best_match_count = match_count
        elif match_count == 1 and best_match_count < 2 and score > best_score:
            # Fallback: accept single-match only if no product has 2+ matches
            best_score = score
            best_match_order = order
            best_match_count = match_count

    return best_match_order


def filter_banned_words(reply_text: str, banned_words: list[str]) -> str:
    """Replace banned words in reply with '***'. Case-insensitive."""
    if not banned_words:
        return reply_text

    result = reply_text
    for word in banned_words:
        if not word:
            continue
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        result = pattern.sub("***", result)

    return result


async def generate_knowledge_reply(
    api_key: str,
    model: str,
    comment_text: str,
    guest_name: str,
    product_context: dict | None,
    system_prompt_override: str | None = None,
) -> str | None:
    """Generate a knowledge-based reply using product context.

    One LLM call that classifies intent and generates reply.
    """
    # Build product info section
    if product_context:
        price_display = _format_price(product_context.get("price_min"), product_context.get("price_max"))
        discount = product_context.get("discount_pct") or 0
        stock_text = "Con hang" if product_context.get("in_stock") else "Het hang"
        stock_qty = product_context.get("stock_qty") or 0
        sold = product_context.get("sold") or 0
        rating = product_context.get("rating") or 0
        rating_count = product_context.get("rating_count") or 0

        voucher_text = ""
        if product_context.get("voucher_info"):
            try:
                vouchers = json.loads(product_context["voucher_info"])
                voucher_text = ", ".join(vouchers) if vouchers else "Khong co"
            except (json.JSONDecodeError, TypeError):
                voucher_text = "Khong co"

        product_section = (
            f"\nThong tin san pham #{product_context.get('product_order', '?')}:\n"
            f"- Ten: {product_context.get('name', 'N/A')}\n"
            f"- Gia: {price_display}\n"
            f"- Giam gia: {discount}%\n"
            f"- Tinh trang: {stock_text} ({stock_qty} san pham)\n"
            f"- Da ban: {sold}+\n"
            f"- Danh gia: {rating}/5 ({rating_count} danh gia)\n"
            f"- Voucher: {voucher_text}\n"
        )
    else:
        product_section = "\nKhong xac dinh duoc san pham cu the tu comment.\n"

    intent_instruction = (
        "Truoc khi tra loi, xac dinh y dinh (intent) cua khach hang:\n"
        "- product_consult: hoi chi tiet/tu van san pham -> tra loi thong tin san pham\n"
        "- stock_inquiry: hoi con hang, con size -> tra loi tinh trang ton kho\n"
        "- price_inquiry: hoi gia, voucher, giam gia -> tra loi gia va khuyen mai\n"
        "- shipping_inquiry: hoi van chuyen, ship, giao hang -> tra loi ve van chuyen\n"
        "- purchase_intent: muon mua, chot don -> huong dan chot don\n"
        "- positive_review: khen, hai long -> cam on\n"
        "- complaint: khieu nai, phan nan -> xin loi va ho tro\n"
        "- other: chao hoi, khong lien quan -> chao va moi xem live\n"
        "Tra loi phu hop voi intent, KHONG tra loi thong tin san pham neu khach khong hoi ve san pham.\n"
    )

    system_prompt = (
        "Ban la nhan vien tu van ban hang tren Shopee Live. "
        "Tra loi ngan gon (toi da 2-3 cau), than thien, co emoji phu hop.\n"
        f"{intent_instruction}"
        f"{product_section}"
    )

    if system_prompt_override:
        system_prompt = f"{system_prompt_override}\n{intent_instruction}{product_section}"

    try:
        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Khach hang {guest_name} binh luan: {comment_text}",
                },
            ],
            max_tokens=200,
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Knowledge reply generation failed: {e}")
        return None


def _format_price(price_min: int | None, price_max: int | None) -> str:
    """Format price range for display."""
    if price_min is None and price_max is None:
        return "Lien he"
    if price_min == price_max or price_max is None:
        return f"{_format_vnd(price_min)}d"
    if price_min is None:
        return f"{_format_vnd(price_max)}d"
    return f"{_format_vnd(price_min)}d - {_format_vnd(price_max)}d"


def _format_vnd(amount: int | None) -> str:
    """Format VND amount (e.g., 135000 -> '135.000')."""
    if amount is None:
        return "0"
    return f"{amount:,}".replace(",", ".")
