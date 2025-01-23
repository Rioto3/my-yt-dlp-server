# Build Stage
FROM python:3.11-alpine AS build

WORKDIR /app

# Install system dependencies
RUN apk update && apk add --no-cache \
    ffmpeg \
    build-base \
    && rm -rf /var/cache/apk/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application Stage
FROM python:3.11-alpine AS runtime

WORKDIR /app

# Install only runtime dependencies (ffmpeg)
RUN apk update && apk add --no-cache \
    ffmpeg \
    && rm -rf /var/cache/apk/*

# Copy entire /usr/local directory to ensure all binaries and libraries are available
COPY --from=build /usr/local /usr/local

# Install uvicorn explicitly in runtime stage
# Verify uvicorn installation and install latest version
RUN pip install --upgrade uvicorn && uvicorn --version

# Copy application code
COPY ./app .

# Ensure uvicorn is available in PATH
# Ensure Python executables like uvicorn are in PATH
ENV PATH="/usr/local/bin:/usr/local/sbin:$PATH"

# Set the python path and run the application
ENV PYTHONPATH=/app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7783"]
