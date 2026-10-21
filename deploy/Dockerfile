# Official Python 3.11.17/bookworm and uv 0.13.1, verified by registry digest.
FROM ghcr.io/astral-sh/uv@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv
FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89
ARG VCS_REF=""
LABEL org.opencontainers.image.revision=$VCS_REF
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
RUN groupadd --gid 10001 telescope && useradd --uid 10001 --gid 10001 --no-create-home telescope
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "telescope_rag.api.container:create_container_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
