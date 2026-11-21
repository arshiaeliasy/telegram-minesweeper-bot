# ربات مینروب تلگرام — تصویر سبک، بدون هیچ وابستگی خارجی.
# اجرا:  docker build -t minesweeper-bot .
#        docker run -d --name minesweeper-bot \
#          -e BOT_TOKEN=123456:ABC-DEF... \
#          -v minesweeper-data:/data \
#          minesweeper-bot
FROM python:3.12-slim

# اجرای بدون بافر و بدون نوشتن .pyc داخل تصویر
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BOT_TOKEN=""

WORKDIR /app

# فقط کد لازم برای اجرا (بدون تست‌ها و فایل‌های توسعه)
COPY bot.py duel.py minesweeper.py ui.py fa.py storage.py telegram_api.py ./
COPY requirements.txt ./

# آمار در این مسیر ذخیره می‌شود؛ با volume ماندگارش کن
VOLUME ["/data"]

# کاربر غیر روت (تصویر python کاربر uid=1000 به نام app را ندارد، خودمان می‌سازیم)
RUN useradd --create-home --uid 10001 runner && mkdir -p /data && chown -R runner:runner /data /app
USER runner

CMD ["python", "bot.py", "--stats-file", "/data/stats.json"]
