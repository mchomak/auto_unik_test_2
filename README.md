# Test Automation — автоматическое прохождение онлайн-тестов

Автоматизация прохождения онлайн-тестов (Moodle) с использованием расширения Chrome **SyncShare** для получения рекомендаций по ответам.

## Требования

- **Python** 3.10+
- **Google Chrome** (актуальная версия)
- **ChromeDriver** — совместимый с установленной версией Chrome
- Расширение **SyncShare** (распакованное)

## Установка

### 1. Клонирование и зависимости

```bash
git clone <repo-url>
cd test_automation
python -m venv venv
source venv/bin/activate   # Linux/macOS
# venv\Scripts\activate    # Windows
pip install -r requirements.txt
```

### 2. ChromeDriver

ChromeDriver должен быть доступен в `PATH`. Selenium 4.x умеет скачивать его автоматически через `selenium-manager`, но при проблемах можно установить вручную:

```bash
# Проверить версию Chrome
google-chrome --version

# Скачать подходящий ChromeDriver:
# https://googlechromelabs.github.io/chrome-for-testing/
```

### 3. Расширение SyncShare

1. Откройте Chrome и перейдите на страницу расширения:
   `chrome://extensions/`
2. Включите **Режим разработчика** (Developer mode) в правом верхнем углу.
3. Установите расширение SyncShare из Chrome Web Store или загрузите его.
4. Нажмите **Подробнее** на карточке расширения и скопируйте его ID.
5. Найдите папку расширения на диске:
   - Linux: `~/.config/google-chrome/Default/Extensions/<ID>/<version>/`
   - macOS: `~/Library/Application Support/Google/Chrome/Default/Extensions/<ID>/<version>/`
   - Windows: `%LOCALAPPDATA%\Google\Chrome\User Data\Default\Extensions\<ID>\<version>\`
6. Укажите путь к этой папке в `.env` как `EXTENSION_PATH`.

### 4. Конфигурация

```bash
cp .env.example .env
```

Отредактируйте `.env`:

| Переменная            | Описание                                           | Пример                         |
|-----------------------|----------------------------------------------------|---------------------------------|
| `LOGIN`               | Логин для авторизации                              | `student@example.com`          |
| `PASSWORD`            | Пароль                                             | `secret123`                    |
| `EXTENSION_PATH`      | Путь к распакованному расширению SyncShare         | `/home/user/.config/.../ext/`  |
| `CHROME_PROFILE_PATH` | Путь к профилю Chrome (для сохранения сессии)      | `./chrome_profile`             |
| `COOKIES_FILE`        | Путь к файлу cookies                               | `./cookies.pkl`                |
| `TEST_URLS`           | URL тестов через запятую                           | `https://lms.example.com/...`  |
| `TEST_MODE`           | `true` — не завершать тест, оставить браузер       | `false`                        |
| `HEADLESS`            | Headless-режим (расширения не работают в headless!) | `false`                        |
| `WAIT_TIMEOUT`        | Таймаут ожидания элементов (сек.)                  | `10`                           |
| `QUESTION_DELAY`      | Задержка между вопросами (сек.)                    | `2`                            |
| `LOG_LEVEL`           | Уровень логирования                                | `INFO`                         |

## Запуск

```bash
python main.py
```

## Структура проекта

```
test_automation/
├── .env.example          # Шаблон переменных окружения
├── .gitignore
├── README.md
├── requirements.txt
├── config.py             # Загрузка конфигурации из .env
├── main.py               # Точка входа
├── bot/
│   ├── __init__.py
│   ├── browser.py        # Инициализация браузера с расширением
│   ├── auth.py           # Авторизация и работа с cookies
│   └── test_solver.py    # Логика прохождения тестов
└── logs/
    └── .gitkeep
```

## Как это работает

1. Запускается Chrome с загруженным расширением SyncShare.
2. Программа авторизуется на платформе (или использует сохранённые cookies).
3. Для каждого URL из `TEST_URLS`:
   - Открывается страница теста.
   - Нажимается кнопка «Пройти тест».
   - На каждом вопросе находятся кнопки расширения SyncShare.
   - Из подменю «Рекомендации» выбирается первый (наиболее вероятный) ответ.
   - Нажимается «Следующая страница» или «Закончить попытку».
4. Логи пишутся в консоль и в `logs/`.

## Тестовый режим

Установите `TEST_MODE=true` в `.env`, чтобы:

- Программа остановилась перед нажатием «Закончить попытку».
- Браузер остался открытым для ручной проверки ответов.
- Нажмите Enter в терминале для продолжения.

## Возможные проблемы

| Проблема                                 | Решение                                                                                  |
|------------------------------------------|------------------------------------------------------------------------------------------|
| `FileNotFoundError: расширение`          | Проверьте `EXTENSION_PATH` в `.env` — путь должен указывать на распакованную папку       |
| `SessionNotCreatedException`             | Обновите ChromeDriver до версии, совместимой с Chrome                                    |
| Расширение не загружается                | Убедитесь, что `HEADLESS=false` — расширения не работают в headless                      |
| Кнопки расширения не найдены             | Убедитесь, что SyncShare активен и имеет данные для текущего теста                       |
| Таймаут при авторизации                  | Проверьте `LOGIN`/`PASSWORD` в `.env` и увеличьте `WAIT_TIMEOUT`                         |
| `cookies.pkl` — ошибка загрузки          | Удалите файл `cookies.pkl` и перезапустите программу                                     |
