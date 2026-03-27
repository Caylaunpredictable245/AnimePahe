FROM python:3.11-slim

# Install system dependencies
USER root
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    aria2 \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy only requirements first to leverage Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the full application code
COPY . .

# Create a non-root user and switch to it for security
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Expose the port your FastAPI app will run on
EXPOSE 8080

# Health check (FastAPI endpoint at /health)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the bot — your bot.py manually starts uvicorn and Telethon
CMD ["python", "bot.py"]
