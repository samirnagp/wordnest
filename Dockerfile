FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd -m -u 1000 app
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY main.py .
COPY public ./public
RUN mkdir -p data && chown -R app:app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://localhost:%s/health'%os.getenv('PORT','8000'))" || exit 1
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
