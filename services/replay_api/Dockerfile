FROM python:3.12-slim AS build
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY packages/ packages/
COPY services/ services/
RUN pip install --no-cache-dir ./packages/playmakers_schema ./packages/pitchsim ./packages/playmakers_stats ./services/stats_mcp ./packages/playmakers_agents ./services/replay_api && pip check

FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY --from=build /opt/venv /opt/venv
RUN useradd --create-home --uid 10001 playmakers
USER playmakers
WORKDIR /home/playmakers
EXPOSE 8000
CMD ["uvicorn", "replay_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
