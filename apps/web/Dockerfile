# syntax=docker/dockerfile:1
# Build from the repo root: docker build -f apps/web/Dockerfile .
# One image for every environment: nginx renders /config.json from the WEB_* variables on start (D17).
FROM --platform=$BUILDPLATFORM node:24.22.0-trixie-slim AS build
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable pnpm
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
COPY packages/contracts/package.json packages/contracts/
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --filter @fs100/web...
COPY packages/contracts packages/contracts
COPY apps/web apps/web
RUN pnpm --filter @fs100/web build

FROM nginxinc/nginx-unprivileged:1.30.6-alpine
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY apps/web/config.json.template /etc/nginx/templates/
COPY --from=build /repo/apps/web/dist/web/browser /usr/share/nginx/html
# The entrypoint's envsubst writes config.json next to index.html (replacing the dev copy from public/).
USER root
RUN chown nginx /usr/share/nginx/html && rm /usr/share/nginx/html/config.json
USER nginx
ENV NGINX_ENVSUBST_OUTPUT_DIR=/usr/share/nginx/html \
    WEB_KEYCLOAK_URL=http://localhost:8080 \
    WEB_KEYCLOAK_REALM=kb \
    WEB_KEYCLOAK_CLIENT_ID=kb-web \
    WEB_API_BASE_URL=http://localhost:3000 \
    WEB_PHOENIX_URL=
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/config.json || exit 1
