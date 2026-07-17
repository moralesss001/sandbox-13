FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV API_MODE=paper
ENV ALLOW_REAL_ORDERS=false
ENV ALLOW_TESTNET_ORDERS=false

CMD ["python", "-m", "src.main", "--help"]
