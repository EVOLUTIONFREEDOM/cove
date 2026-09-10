FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY run.py .

RUN mkdir -p /data

ENV HOST=0.0.0.0
ENV PORT=8787
ENV DATABASE_URL=sqlite:////data/cove.db
EXPOSE 8787

CMD ["python", "run.py"]
