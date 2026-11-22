# Contributing to QuizForge

Дякуємо за інтерес до проєкту!

## Як внести зміни

1. Форкніть репозиторій
2. Створіть гілку: `git checkout -b feature/your-feature`
3. Внесіть зміни
4. Запустіть тести: `python -m pytest tests/ -v`
5. Створіть Pull Request

## Стиль коду

- Python 3.11+
- Типізація там, де це доречно
- Коментарі українською або англійською
- Мінімальні зміни, які вирішують задачу

## Тести

Перед PR обов'язково:

```bash
pip install -r requirements.txt pytest
python -m pytest tests/ -v
```

## Структура

- `client/` — інтерфейс тестування
- `admin/` — адмін-панель
- `core/` — спільна логіка (БД, OTP, звіти)
- `tests/` — юніт-тести

Питання та пропозиції — через Issues.
