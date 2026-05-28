# 🤖 AIPLUS — Телеграм бот для генерации договоров

## Что делает бот
1. Менеджер выбирает ИП (Махсутов или Білім Орталығы)
2. Скидывает PDF удостоверения родителя
3. Скидывает PDF документа ребёнка
4. Бот автоматически извлекает данные (PyMuPDF + Tesseract OCR — бесплатно)
5. Менеджер вводит остальные данные
6. Получает готовый .docx договор

## Нужен только один токен — токен бота в Telegram (бесплатно)

---

## Установка

### Шаг 1 — Получите токен бота
1. Откройте Telegram → @BotFather → /newbot
2. Придумайте имя и username
3. Скопируйте токен

### Шаг 2 — Установите зависимости
```bash
pip install -r requirements.txt
# Tesseract OCR (для сканов):
# Ubuntu/Debian: sudo apt install tesseract-ocr tesseract-ocr-rus
# Mac: brew install tesseract tesseract-lang
# Windows: скачайте с https://github.com/UB-Mannheim/tesseract/wiki
```

### Шаг 3 — Запустите
```bash
export BOT_TOKEN="ваш_токен"
python bot.py
```

---

## Деплой на Railway (бесплатно, 24/7)

1. Зарегистрируйтесь на https://railway.app
2. New Project → Deploy from GitHub
3. Загрузите файлы в GitHub репозиторий
4. В Railway добавьте переменную: BOT_TOKEN = ваш токен
5. Добавьте в Dockerfile установку Tesseract (см. ниже)

### Dockerfile для Railway:
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-rus && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
```

---

## Команды бота
- /start — начать новый договор
- /cancel — отменить текущий процесс
