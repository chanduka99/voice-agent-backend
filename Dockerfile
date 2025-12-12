# Use Python 3.10+ as required by pyproject.toml
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies if needed
RUN apt-get update && apt-get install -y \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY app/ ./app/

# Install the package in editable mode
RUN pip install --no-cache-dir -e .

# Set working directory to app for running the application
WORKDIR /app/app

# Expose port 8000
EXPOSE 8000

# Run uvicorn (--reload disabled for production, use --reload in docker-compose for development)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

