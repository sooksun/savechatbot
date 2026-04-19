import httpx
from ..config import get_settings

settings = get_settings()
API = "https://api.line.me/v2/bot"


async def get_profile(user_id: str, group_id: str | None = None) -> dict:
    url = (
        f"{API}/group/{group_id}/member/{user_id}"
        if group_id
        else f"{API}/profile/{user_id}"
    )
    headers = {"Authorization": f"Bearer {settings.LINE_CHANNEL_ACCESS_TOKEN}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, headers=headers)
        if r.status_code != 200:
            return {}
        return r.json()


async def reply_message(reply_token: str, text: str) -> None:
    """Reply to a LINE event. Text is truncated to 5000 chars per LINE limits."""
    headers = {
        "Authorization": f"Bearer {settings.LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text[:5000] or "(empty)"}],
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(f"{API}/message/reply", headers=headers, json=body)


async def push_message(to: str, text: str) -> None:
    headers = {
        "Authorization": f"Bearer {settings.LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {"to": to, "messages": [{"type": "text", "text": text[:5000] or "(empty)"}]}
    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(f"{API}/message/push", headers=headers, json=body)


async def get_group_summary(group_id: str) -> dict:
    headers = {"Authorization": f"Bearer {settings.LINE_CHANNEL_ACCESS_TOKEN}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{API}/group/{group_id}/summary", headers=headers)
        if r.status_code != 200:
            return {}
        return r.json()
