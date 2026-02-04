FROM python:3.11-slim

WORKDIR /app

# Install SSH client and bash for running WireGuard setup script
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    openssh-client \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
