FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Seed database at build time
RUN python -m src.database.seed_databases

# Expose port
EXPOSE 8000

# Run the LLMSQL server
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
