# Minimal image: no third-party packages are required at runtime.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/packages

WORKDIR /app
COPY . /app

# Standard library only - nothing to install.
RUN python -c "import sys; print('python', sys.version.split()[0])"

EXPOSE 8611

CMD ["python", "-m", "contextcanon_cli", "doctor"]
