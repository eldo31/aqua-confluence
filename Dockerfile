# ---- base image
FROM python:3.11-slim

# ---- system deps (ffmpeg for pydub)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# ---- workdir
WORKDIR /app

# ---- python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- app code
COPY src ./src
# (optionnel si tu as d'autres fichiers utiles à runtime)
# COPY Procfile render.yaml apt.txt ./

# ---- runtime env
ENV PYTHONUNBUFFERED=1
# Koyeb fournit la variable PORT automatiquement

# ---- expose (facultatif – informatif)
EXPOSE 8080

# ---- command (gunicorn -> Flask app in src/main.py)
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:${PORT}", "src.main:app"]
