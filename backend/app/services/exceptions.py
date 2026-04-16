"""Domain-specific exceptions for Shopee interactions."""


class ShopeeError(Exception):
    """Base class for Shopee upstream errors."""


class ShopeeAuthError(ShopeeError):
    """401 / 403 from Shopee — credentials are invalid. Stop scanning."""


class ShopeeRateLimitError(ShopeeError):
    """429 from Shopee — client should back off."""


class ShopeeServerError(ShopeeError):
    """5xx from Shopee — transient, safe to retry."""
