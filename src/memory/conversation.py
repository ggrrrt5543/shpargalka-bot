"""
Управление историей диалога пользователя.

Хранит последние N сообщений, обрезает по токенам,
сбрасывает по таймауту неактивности.
"""
from src.db import conversations as db_conv


class ConversationMemory:
    """Обёртка над db.conversations с лимитами и trim."""

    def __init__(self, max_messages: int = 10, timeout_minutes: int = 30):
        self.max_messages = max_messages
        self.timeout_minutes = timeout_minutes

    async def get_history(self, user_id: int) -> list[dict]:
        """Возвращает историю в формате OpenAI messages[].

        Автоматически обрезает по таймауту и лимиту токенов.
        """
        messages = await db_conv.get_history(
            user_id,
            limit=self.max_messages,
            timeout_minutes=self.timeout_minutes,
        )
        return self._trim_to_token_limit(messages, max_tokens=8000)

    async def add_message(self, user_id: int, role: str, content: str) -> None:
        """Сохраняет сообщение (обрезает длинные ответы до 2000 символов)."""
        await db_conv.add_message(user_id, role, content[:2000])

    async def clear(self, user_id: int) -> None:
        """Очищает историю пользователя."""
        await db_conv.clear(user_id)

    def _trim_to_token_limit(
        self, messages: list[dict], max_tokens: int = 8000
    ) -> list[dict]:
        """Обрезает старые сообщения если суммарный размер превышает лимит.

        Грубая оценка: ~4 символа = 1 токен.
        """
        total = sum(len(m["content"]) // 4 for m in messages)
        while total > max_tokens and messages:
            removed = messages.pop(0)
            total -= len(removed["content"]) // 4
        return messages
