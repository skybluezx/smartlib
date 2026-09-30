ARG PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.14.7-slim-bookworm
FROM ${PYTHON_IMAGE} AS application
ARG SMARTLIB_PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN sed -i \
        -e 's|http://deb.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' \
        -e 's|http://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
RUN addgroup --system smartlib && adduser --system --ingroup smartlib smartlib
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --index-url "${SMARTLIB_PIP_INDEX_URL}" \
    fastapi==0.141.1 \
    httpx==0.28.1 \
    networkx==3.6.1 \
    python-multipart==0.0.32 \
    pydantic==2.13.4 \
    "psycopg[binary]==3.3.4" \
    psycopg-pool==3.3.1 \
    pypinyin==0.55.0 \
    uvicorn==0.52.4
COPY src ./src
COPY scripts ./scripts
ENV PYTHONPATH=/app/src

FROM application AS test
ARG SMARTLIB_PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "${SMARTLIB_PIP_INDEX_URL}" \
    mypy==2.3.1 \
    pytest==9.1.1 \
    ruff==0.16.3
COPY mypy.ini ./mypy.ini
COPY tests ./tests
USER smartlib
CMD ["pytest", "-q"]

FROM application AS runtime
USER smartlib
EXPOSE 8080
CMD ["uvicorn", "smartlib_platform.entrypoints.http:app", "--host", "0.0.0.0", "--port", "8080"]
