# Use Python 3.11 slim image
FROM python:3.11-slim-bookworm

# Install Astral's uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Enable bytecode compilation for performance
ENV UV_COMPILE_BYTECODE=1

# Copy dependency specifications first to leverage Docker layer caching
COPY pyproject.toml uv.lock ./

# Install project dependencies
RUN uv sync --frozen --no-install-project --no-dev

# Copy application source code
COPY . .

# Install project itself
RUN uv sync --frozen --no-dev

# Place virtual environment on PATH
ENV PATH="/app/.venv/bin:$PATH"

# Expose FastAPI service port
EXPOSE 8000

# Default command to run FastAPI application
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
