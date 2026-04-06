"""Process tweets through OpenRouter AI for translation and analysis."""
import logging
import httpx
from config import get_api_key, get_model

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — помощник для мониторинга крипто-розыгрышей в Twitter/X.

Твоя задача:
1. Перевести твит на русский язык
2. Если в твите есть задание (подписаться, ретвитнуть, написать комментарий и т.д.) — четко расписать шаги
3. Если есть дедлайн или условия участия — выделить их
4. Если нужно написать комментарий или ответить на вопрос — предложи 2-3 варианта ответа/комментария на английском
5. Если это не розыгрыш/giveaway — просто перевести

Формат ответа:
📝 **Перевод:**
<перевод на русский>

🎯 **Задания:** (если есть)
<список действий>

💬 **Идеи для комментария:** (если нужно писать комментарий/ответ)
1. <вариант на английском>
2. <вариант на английском>
3. <вариант на английском>

⏰ **Дедлайн:** (если указан)
<дата/время>

💰 **Приз:** (если указан)
<что разыгрывают>

Будь кратким и точным. Не добавляй лишнего."""


async def process_tweet(tweet_text: str, username: str) -> str:
    """Send tweet to OpenRouter for translation and analysis."""
    api_key = get_api_key()
    model = get_model()

    if not api_key:
        return f"⚠️ OpenRouter API key не настроен. Используй /key\n\nОригинал:\n{tweet_text}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"Твит от @{username}:\n\n{tweet_text}"},
                    ],
                    "max_tokens": 1500,
                    "temperature": 0.3,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"OpenRouter error: {e}")
        return f"⚠️ Ошибка AI ({model}): {e}\n\nОригинал:\n{tweet_text}"
