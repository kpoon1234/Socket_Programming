FROM node:22-bookworm-slim AS styles
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY web ./web
RUN npm run build:css

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 chat \
    && useradd --uid 10001 --gid chat --no-create-home --shell /usr/sbin/nologin chat \
    && mkdir /data && chown chat:chat /data
COPY server.py client_network.py protocol.py state_store.py web_bridge.py ./
COPY feature/summarize ./feature/summarize
COPY feature/E2EE ./feature/E2EE
COPY web ./web
COPY --from=styles /build/web/assets/styles.css ./web/assets/styles.css
USER chat
CMD ["python", "-u", "web_bridge.py", "--host", "0.0.0.0", "--tcp-host", "server"]
