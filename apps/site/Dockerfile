# The public website: static files behind nginx on Cloud Run.
FROM nginx:1.27-alpine
ENV PORT=8080 CONSOLE_URL=http://localhost:3000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY index.html styles.css favicon.svg /usr/share/nginx/html/
