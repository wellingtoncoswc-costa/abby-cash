# syntax=docker/dockerfile:1.7
# contexto de build: ../web (ver compose). Mesma origem da API: sem URL de API embutida.
FROM node:22-alpine AS build
WORKDIR /w
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /w/dist /usr/share/nginx/html
COPY <<'CONF' /etc/nginx/conf.d/default.conf
server {
    listen 8080;
    root /usr/share/nginx/html;
    index index.html;
    location / { try_files $uri /index.html; }
    location /assets/ { add_header Cache-Control "public, max-age=31536000, immutable"; }
    location = /sw.js { add_header Cache-Control "no-cache"; }
    location = /index.html { add_header Cache-Control "no-cache"; }
}
CONF
