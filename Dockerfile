FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir uv==0.13.5
WORKDIR /app
COPY . .
ARG INSTALL_SEMANTIC=false
RUN if [ "$INSTALL_SEMANTIC" = "true" ]; then uv sync --frozen --no-dev --extra semantic; else uv sync --frozen --no-dev; fi
RUN useradd --uid 10001 --create-home app && mkdir -p /app/artifacts /app/data /var/data/artifacts /home/app/.ssh && chmod 0700 /home/app/.ssh && chown -R app:app /app /var/data /home/app
USER app
EXPOSE 8000 8501
CMD ["uvicorn", "triagedesk.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
