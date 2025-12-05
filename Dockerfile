# Dockerfile
FROM python:3.11-slim

# Install OS deps for psycopg2 and unzip
RUN apt-get update && apt-get install -y gcc libpq-dev unzip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first (cache layer)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy app files
COPY . /app

# Expose port
EXPOSE 5000

# Default environment variables (can be overridden)
ENV FLASK_ENV=production
ENV FLASK_APP=app.py
ENV IMAGE_DIR=/app/static/img
ENV IMAGE_PRINCIPALE=image_principale_ent.jpg

# Create directory for images (user can mount here)
RUN mkdir -p /app/static/img

# Entrypoint: ensure DB tables exist then start
CMD ["sh", "-c", "python -c 'from models import initialize; initialize(); print(\"DB initialized\")' && python app.py --host=0.0.0.0"]
