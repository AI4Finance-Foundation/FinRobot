FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
# - build-essential: needed to compile numpy<2 from source on Python 3.13
# - libfreetype6, libfontconfig1: matplotlib font rendering
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential libfreetype6 libfontconfig1 && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements-equity.txt .
RUN pip install --no-cache-dir -r requirements-equity.txt && \
    apt-get purge -y --auto-remove build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy source code
COPY . .

EXPOSE 8001

CMD ["uvicorn", "finrobot_equity.web_app.main:app", "--host", "0.0.0.0", "--port", "8001"]
