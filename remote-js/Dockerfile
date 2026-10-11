# Media Manager (Next.js, Node.js runtime). Bun is used only to install the
# packages from the frozen lockfile. Base images are pinned by digest.
#   oven/bun:1.4.2-alpine  (created 2026-09-05)
#   node:24-alpine         (Node 24.21.0, created 2026-09-17)

FROM oven/bun:1.4.2-alpine@sha256:d888c0ae6c86d7866ff10c5aafdd9077b36aee6455b33dd270fb93c0dd5cef6f AS deps
WORKDIR /app
COPY package.json bun.lock bunfig.toml ./
# Bun does not run dependency lifecycle scripts unless the package is in
# trustedDependencies (there is none).
RUN bun install --frozen-lockfile

FROM oven/bun:1.4.2-alpine@sha256:d888c0ae6c86d7866ff10c5aafdd9077b36aee6455b33dd270fb93c0dd5cef6f AS prod-deps
WORKDIR /app
COPY package.json bun.lock bunfig.toml ./
# server.ts and scripts/*.ts load postgres and the AWS SDK outside of the
# Next.js bundle, so the run-time image needs the full production packages,
# not only the files that the standalone trace found. Remove next and sharp
# here: the standalone output adds the trimmed copies that the server needs
# (the full next package has build-only files, for example the SWC binaries).
RUN bun install --frozen-lockfile --production \
 && rm -rf node_modules/next node_modules/@next node_modules/sharp node_modules/@img

FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN node node_modules/next/dist/bin/next build

FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS runtime
# ffmpeg gives ffprobe (upload duration) and the test fixture generator.
RUN apk add --no-cache ffmpeg ca-certificates
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080
COPY --from=prod-deps /app/node_modules ./node_modules
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY package.json server.ts ./
COPY src/server ./src/server
COPY scripts ./scripts
USER node
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
CMD ["node", "server.ts"]
