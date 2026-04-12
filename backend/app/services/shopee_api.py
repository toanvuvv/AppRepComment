import httpx

SHOPEE_HEADERS = {
    "accept": "application/json",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json",
    "language": "en",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "x-env": "live",
    "x-region": "vn",
    "x-region-domain": "vn",
    "x-region-timezone": "+0700",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "referer": "https://creator.shopee.vn/",
}


async def get_live_sessions(cookies: str) -> dict:
    """Fetch session list from Shopee Creator API"""
    url = (
        "https://creator.shopee.vn/supply/api/lm/sellercenter/realtime/sessionList"
        "?page=1&pageSize=10&name=&orderBy=&sort="
    )
    headers = {**SHOPEE_HEADERS, "cookie": cookies}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, timeout=15.0)
        resp.raise_for_status()
        return resp.json()


async def get_comments(cookies: str, session_id: int, start_timestamp: int) -> list:
    """Fetch comments from a live session"""
    url = (
        "https://creator.shopee.vn/supply/api/lm/sellercenter/realtime/"
        f"dashboard/livestream/comments?sessionId={session_id}"
        f"&startTimestamp={start_timestamp}"
    )
    headers = {**SHOPEE_HEADERS, "cookie": cookies}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        items = (
            data.get("data", {}).get("comments")
            or data.get("data", {}).get("list")
            or data.get("data")
            or []
        )
        if not isinstance(items, list):
            items = []
        return items
