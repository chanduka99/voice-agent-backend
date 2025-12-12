# Use Python 3.10+ as required by pyproject.toml
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install uv
RUN pip install uv

# Copy project files
COPY pyproject.toml ./
COPY app/ ./app/

# Make sure README.md is included
COPY README.md /app/README.md

# Install dependencies using uv sync
RUN uv sync

# Set working directory to app for running the application
WORKDIR /app/app

# Expose port 8000
EXPOSE 8000

# Run uvicorn using uv run (--reload disabled for production, use --reload in docker-compose for development)
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

