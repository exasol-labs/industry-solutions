FROM python:3.12.16-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY demo_dashboard.py ./
COPY 07_refresh_analytics_features.sql ./

EXPOSE 8501

CMD ["python", "-m", "streamlit", "run", "demo_dashboard.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
