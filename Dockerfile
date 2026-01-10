FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# sisteminiai minimum
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# kopijuojam visą projektą
COPY . /app

# python deps (jei yra)
RUN if [ -f requirements.txt ]; then \
      pip install --no-cache-dir -r requirements.txt ; \
    elif [ -f bot/requirements.txt ]; then \
      pip install --no-cache-dir -r bot/requirements.txt ; \
    else \
      echo "No requirements.txt found, skipping pip install"; \
    fi

CMD ["python", "run_paper.py"]
