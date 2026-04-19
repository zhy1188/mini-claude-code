FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .

RUN pip install --no-cache-dir \
    rich>=13.0 \
    pydantic>=2.0 \
    anthropic>=0.39.0 \
    openai>=1.50.0 \
    httpx>=0.27.0 \
    tiktoken>=0.8.0 \
    pytest>=8.0 \
    pytest-asyncio>=0.24.0 \
    hatchling

COPY src/ src/
COPY tests/ tests/
COPY nexus.toml .
COPY .nexus.md .

ENV PYTHONPATH=/app/src

CMD ["python", "-m", "nexusagent"]
