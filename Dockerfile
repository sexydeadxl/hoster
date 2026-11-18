FROM python:3.11-slim

# Install Node.js (for Railway CLI), curl, git, and required build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    gnupg \
    build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @railway/cli \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency definition and install Python libraries
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Ensure working data directories exist
RUN mkdir -p stark_data upload_bots

# Expose web service port for Render health check / keep alive
EXPOSE 8080
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "main.py"]
