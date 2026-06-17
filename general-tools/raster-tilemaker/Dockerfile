# syntax=docker/dockerfile:1
FROM ghcr.io/osgeo/gdal:alpine-normal-3.12.4 AS base

ENV PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_CACHE_DIR='/var/cache/pypoetry' \
    POETRY_HOME='/usr/local' \
    APP_PATH="/raster-tilemaker" \
    CHART_OUTPUT="/processed/pmtiles" 

# application user
RUN adduser -u 1000 -D -H app

RUN mkdir -p $APP_PATH $CHART_OUTPUT $CONFIGURATION_INPUT \
    && chown -R app:app $APP_PATH $CHART_OUTPUT $CONFIGURATION_INPUT
VOLUME ["$CHART_OUTPUT"]
WORKDIR $APP_PATH

FROM base AS builder

RUN apk add --no-cache curl build-base \
    && curl -sSL https://install.python-poetry.org | python -

COPY . $APP_PATH/

RUN poetry config virtualenvs.in-project true \
    && poetry config virtualenvs.options.system-site-packages true \
    && poetry install --only=main --no-ansi 

FROM base AS runtime

ENV PATH="$APP_PATH/.venv/bin:${PATH}" \
    VIRTUAL_ENV="$APP_PATH/.venv"

COPY --from=builder $APP_PATH/ ./
RUN chown -R app:app $APP_PATH

USER app:app

STOPSIGNAL SIGTERM

ENTRYPOINT ["python", "-m", "raster_tilemaker.build_tiles"]
CMD ["-h"]