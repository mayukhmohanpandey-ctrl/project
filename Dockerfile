FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PORT=8000 TRUST_PROXY=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py engine.py llm.py ./
COPY static ./static
RUN useradd -m app && chown -R app /app
USER app
EXPOSE 8000
CMD gunicorn app:app --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:${PORT}
