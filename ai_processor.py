"""Process tweets through OpenRouter AI for translation and analysis."""
import logging
import httpx
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — помощник для мониторинга крипто-розыгрышей в Twitter/X.

Твоя задача:
1. Перевести твит на русский язык
2. Если в твите есть задание (подписаться, ретвитнуть, написать комментарий и т.д.) — четко расписать шаги
3. Если есть дедлайн или условия участия — выделить их
4. Если это не розыгрыш/giveaway — просто перевести

Формат ответа:
📝 **Перевод:**
<перевод на русский>

🎯 **Задания:** (если есть)
<список действий>

⏰ **Дедлайн:** (если указан)
<дата/время>

💰 **Приз:** (если указан)
<что разыгрывают>

Будь кратким и точным. Не добавляй лишнего."""


async def process_tweet(tweet_text: str, username: str) -> str:
    """Send tweet to OpenRouter for translation and analysis."""
    if not OPENROUTER_API_KEY:
        return f"⚠️ OpenRouter API key не настроен\n\nОригинал:\n{tweet_text}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"Твит от @{username}:\n\n{tweet_text}"},
                    ],
                    "max_tokens": 1000,
                    "temperature": 0.3,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"OpenRouter error: {e}")
        return f"⚠️ Ошибка AI: {e}\n\nОригинал:\n{tweet_text}"
