# Docker Setup for FastAPI App

This document explains how to run the FastAPI application using Docker.

## Prerequisites

- Docker installed on your system
- Docker Compose (optional, for easier management)

## Building the Docker Image

```bash
docker build -t bidi-demo .
```

## Running the Container

### Option 1: Using Docker Run (with environment variables)

```bash
docker run -d \
  --name bidi-demo \
  -p 8000:8000 \
  -e GOOGLE_API_KEY=your_api_key_here \
  -e OTHER_ENV_VAR=value \
  bidi-demo
```

### Option 2: Using Docker Compose

1. Create a `.env` file in the `app/` directory with your environment variables:
   ```
   GOOGLE_API_KEY=your_api_key_here
   OTHER_ENV_VAR=value
   ```

2. Run with docker-compose:
   ```bash
   docker-compose up -d
   ```

   Or for development with auto-reload:
   ```bash
   docker-compose up
   ```
   (Make sure to uncomment the `command` line in docker-compose.yml for reload)

### Option 3: Using Docker Compose with inline environment variables

Edit `docker-compose.yml` and add your environment variables under the `environment` section:

```yaml
environment:
  GOOGLE_API_KEY: your_api_key_here
  OTHER_ENV_VAR: value
```

Then run:
```bash
docker-compose up -d
```

## Accessing the Application

Once the container is running, access the application at:
- http://localhost:8000

## Viewing Logs

```bash
docker logs -f bidi-demo
```

Or with docker-compose:
```bash
docker-compose logs -f
```

## Stopping the Container

```bash
docker stop bidi-demo
docker rm bidi-demo
```

Or with docker-compose:
```bash
docker-compose down
```

## Development Mode

For development with auto-reload, uncomment the `command` line in `docker-compose.yml` and use:
```bash
docker-compose up
```

This will enable hot-reload when you make changes to the code.


