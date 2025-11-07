# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:20-bullseye
FROM ${NODE_IMAGE} AS build

WORKDIR /usr/src/app

ENV PNPM_HOME=/root/.local/share/pnpm
ENV PATH="$PNPM_HOME:$PATH"

RUN corepack enable

COPY package.json pnpm-lock.yaml ./

ARG VITE_API_BASE_URL=/api/v1
ARG DASHBOARD_BASE_URL=/

ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV DASHBOARD_BASE_URL=$DASHBOARD_BASE_URL

RUN pnpm install --frozen-lockfile

COPY tsconfig*.json ./
COPY vite.config.ts ./
COPY eslint.config.js ./
COPY knip.config.ts ./
COPY components.json ./
COPY public ./public
COPY src ./src

RUN pnpm build

FROM node:20-alpine AS runtime

ARG DASHBOARD_BASE_URL=/

WORKDIR /srv/dashboard
COPY --from=build /usr/src/app/dist ./dist
COPY server.mjs ./server.mjs

ENV NODE_ENV=production
ENV DASHBOARD_BASE_URL=$DASHBOARD_BASE_URL
ENV PORT=4173

EXPOSE 4173

CMD ["node", "server.mjs"]
