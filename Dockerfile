# valheimdisplay next to a Valheim server running in Docker (or anywhere).
#   docker build -t valheimdisplay .
#   docker run -d -p 8080:8080 \
#     -v /path/to/worlds_local/MyWorld:/world:ro \
#     -v /path/to/valheim_server_Data:/game:ro \
#     -v valheimdisplay-data:/data \
#     valheimdisplay
# Player stats: also mount the server's log file and add  -e VALHEIM_LOG=/log/server.log -v /path/to/log:/log:ro
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
# some of UnityPy's decoders have no prebuilt wheel for every platform (e.g. arm64 Linux)
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ && rm -rf /var/lib/apt/lists/* \
 && uv sync --frozen --no-dev --no-install-project
COPY tools tools
COPY web web
ENV VALHEIM_LOG=none
EXPOSE 8080
VOLUME /data
CMD ["sh", "-c", "exec uv run --frozen --no-dev python tools/valheimdisplay.py --home /data --world /world --game /game --log \"$VALHEIM_LOG\""]
