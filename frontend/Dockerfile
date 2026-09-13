# --- Stage 1: dependencies ----------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app

# `npm ci` installs exactly what package-lock.json pins — reproducible, and
# faster than `npm install` because it skips dependency resolution.
COPY package.json package-lock.json ./
RUN npm ci

# --- Stage 2: build ------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* variables are inlined into the JavaScript bundle at BUILD
# time, not read at runtime — so the API URL has to be supplied here.
# Changing it later means rebuilding the image.
ARG NEXT_PUBLIC_API_URL=http://localhost:8080
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# --- Stage 3: runtime ----------------------------------------------------
FROM node:22-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# `output: "standalone"` in next.config.ts makes Next emit a self-contained
# server plus only the node_modules it actually uses. Without it this copy
# fails — the two settings go together.
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

CMD ["node", "server.js"]
