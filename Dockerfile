FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# pytesseract invokes a system executable. OpenCV also needs these runtime libs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng libgl1 libglib2.0-0t64 \
    && tesseract --version \
    && rm -rf /var/lib/apt/lists/*

COPY requirements ./requirements

RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements/dev.txt

COPY . .

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
