FROM node:20-alpine AS build
WORKDIR /app
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY web/40-config.sh /docker-entrypoint.d/40-config.sh
RUN chmod +x /docker-entrypoint.d/40-config.sh && mkdir -p /etc/nginx/playmakers
# API_UPSTREAM="" disables the /api proxy; then set API_BASE to the API's public URL.
ENV API_BASE=/api API_UPSTREAM=http://api:8000
EXPOSE 80
