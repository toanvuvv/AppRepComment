# syntax=docker/dockerfile:1.7
FROM node:20-alpine AS build

WORKDIR /app

# Build-time API key injected into the bundle. Override at build:
#   docker compose build --build-arg VITE_APP_API_KEY=xxx frontend
ARG VITE_APP_API_KEY=""
ENV VITE_APP_API_KEY=${VITE_APP_API_KEY}

COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts index.html ./
COPY src ./src

RUN npm run build

# ---- Runtime: nginx serving static bundle + reverse proxy /api ----
FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
