# Перший запуск QuizForge

## Варіант 1: Портативна збірка (рекомендовано)

1. Завантажте архів `QuizForge-Portable-Windows.zip` (або Linux) з Releases.
2. Розпакуйте в будь-яку папку (наприклад `C:\QuizForge`).
3. Відкрийте `config.json` і заповніть:
   - `organization.name` — назва вашої організації
   - `smtp` — дані поштового сервера (для OTP-кодів)
   - `allowed_domains` — дозволені домени пошти (наприклад `["company.com"]`)
   - `report_recipients` — кому надсилати звіти
4. Запустіть `QuizForge-Admin.exe` (або `QuizForge-Admin` на Linux).
5. При першому запуску встановіть пароль адміністратора.
6. У вкладці **Тести** створіть тест (або імпортуйте з Excel).
7. У вкладці **Студенти** додайте учасників (ПІБ + email).
8. Запустіть `QuizForge-Client.exe` на комп’ютерах учасників.
9. Учасник вводить пошту → отримує OTP-код → проходить тест.

## Варіант 2: З вихідного коду

```bash
git clone https://github.com/YOUR_ORG/QuizForge.git
cd QuizForge
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
cp config.json.example config.json
# Відредагуйте config.json
python -m admin.main            # адмін-панель
python -m client.main           # клієнт
```

## Мінімальні налаштування SMTP

```json
"smtp": {
  "host": "smtp.gmail.com",
  "port": 587,
  "security": "starttls",
  "username": "your@gmail.com",
  "password": "app-password",
  "from_address": "your@gmail.com",
  "from_name": "QuizForge"
}
```

> Для Gmail використовуйте App Password, не звичайний пароль.

## Перевірка

- Адмін відкривається і приймає пароль
- Тест створюється
- Студент додається
- Клієнт надсилає OTP (перевірте пошту)
- Тест проходиться до кінця

## Часті проблеми

| Проблема | Рішення |
|----------|---------|
| Не надходить код | Перевірте SMTP, allowed_domains, спам |
| Помилка БД | Видаліть `securetest.db` і запустіть знову |
| Лого не видно | Переконайтеся, що папка `assets` поруч із exe |
| Вікно не відкривається | Запустіть з консолі, щоб побачити помилку |
