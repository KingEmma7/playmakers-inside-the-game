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
RUN chmod +x /docker-entrypoint.d/40-config.sh
ENV API_BASE=/api
EXPOSE 80
