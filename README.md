# Cargonovo Automation Bot

Автоматизация логистики: синхронизация Google Sheets ↔ Bitrix24 CRM.

## Модули

- `google_sync.py` — синхронизация Google Sheets → CRM
- `crm_watcher.py` — отслеживание изменений CRM → Google Sheets
- `chat_bot.py` — обработка команд из чатов
- `file_processor.py` — обработка файлов из чатов

## Команды бота

```

## Деплой

Автоматический деплой через GitHub Actions при push в `main`.
