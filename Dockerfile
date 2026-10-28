# Runs on Hugging Face Spaces (Docker), Render, Railway or any VM.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python tools/generate_test_docs.py && python tools/evaluate.py > /dev/null
ENV PORT=7860
EXPOSE 7860
CMD gunicorn -w 1 -t 120 -b 0.0.0.0:$PORT app.app:app
