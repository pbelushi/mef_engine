FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt requirements-ia.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-ia.txt -r requirements-web.txt

COPY mef_engine ./mef_engine
COPY web ./web

# Cloud Run injeta a porta real em $PORT; o default 8501 cobre execução local.
ENV PORT=8501
EXPOSE 8501

CMD ["sh", "-c", "streamlit run web/app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true"]
