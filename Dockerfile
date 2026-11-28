FROM python:3.11-slim-bookworm

# 1. Runtime, Memory & Timezone Environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MALLOC_ARENA_MAX=2 \
    MALLOC_TRIM_THRESHOLD_=131072 \
    TZ="Asia/Kolkata"

WORKDIR /app

# 2. Runtime system deps only (ffmpeg for ffprobe media fallback + tzdata).
# All Python deps in requirements.txt ship prebuilt wheels/pure-Python, so
# gcc / python3-dev / libffi-dev / git are not needed (~250MB+ lighter & faster).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tzdata \
    && ln -fs /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# 3. Install Python dependencies (cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# 4. Copy Application Source Code
COPY . .

# 5. Expose web server port (synced with info.py PORT=8080)
EXPOSE 8080

# 6. Run with -O (strips asserts and reduces memory overhead)
CMD ["python", "-O", "bot.py"]
