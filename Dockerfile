FROM python:3.11-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Change the working directory to the `app` directory
WORKDIR /code

# Copy the project into the image
COPY . /code

# Install dependencies
RUN uv sync --frozen --no-cache --no-dev

# Expose port
EXPOSE 8080

# Run the application
CMD ["uv", "run", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8080"]
