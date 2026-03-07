FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

COPY luckypot/ luckypot/
COPY lucky_pot.py ./

CMD ["uv", "run", "python", "lucky_pot.py"]
