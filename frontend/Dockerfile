FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm install --no-audit --no-fund

COPY . .

ARG VITE_API_URL=""
ARG VITE_GOOGLE_CLIENT_ID=""
ENV VITE_API_URL=$VITE_API_URL \
    VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID

RUN npm run build

FROM nginx:1.27-alpine

ARG VITE_API_URL=""
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
# CSP connect-src potrzebuje originu API (bez ścieżki). Pusty VITE_API_URL: frontend używa
# domyślnego http://localhost:8000/api/v1 (src/api/client.js). Adres względny: wystarcza 'self'.
RUN api_url="${VITE_API_URL:-http://localhost:8000/api/v1}" \
    && api_origin="$(printf '%s' "$api_url" | sed -nE 's#^(https?://[^/]+).*#\1#p')" \
    && sed -i "s#__API_ORIGIN__#${api_origin}#" /etc/nginx/snippets/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
