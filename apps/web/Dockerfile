ARG NODE_IMAGE=public.ecr.aws/docker/library/node:22-alpine
ARG NGINX_IMAGE=public.ecr.aws/docker/library/nginx:1.28-alpine
ARG VITE_SMARTLIB_DEMO_MODE=true

FROM ${NODE_IMAGE} AS build
ARG VITE_SMARTLIB_DEMO_MODE=true

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html vite.config.ts vitest.config.ts openapi-ts.config.ts playwright.config.ts eslint.config.js tsconfig.json tsconfig.app.json tsconfig.node.json ./
COPY scripts ./scripts
COPY e2e ./e2e
COPY src ./src
COPY public ./public

ENV VITE_SMARTLIB_DEMO_MODE=${VITE_SMARTLIB_DEMO_MODE}
RUN npm run typecheck && npm run lint && npm run test && npm run build

FROM ${NGINX_IMAGE} AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=6 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
