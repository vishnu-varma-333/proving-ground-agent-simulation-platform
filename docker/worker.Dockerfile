# The worker needs the WHOLE workspace, not just pg_worker's own code:
# MockServiceToolbox launches orders_service/payments_service/email_service
# as subprocesses (python -m <service>), so those packages have to be
# installed in the same venv this image runs - one shared uv workspace
# sync, same as local dev, not a from-scratch minimal image per package.
#
# Build and push from the repo root:
#   docker build -f docker/worker.Dockerfile -t localhost:5002/pg-worker:dev .
#   docker push localhost:5002/pg-worker:dev

FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY services/ services/
COPY agents/ agents/
COPY sdk/ sdk/
COPY platform/ platform/

RUN uv sync --all-packages --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

ENTRYPOINT ["python", "-m", "pg_worker"]
CMD ["--once"]
