FROM alpine:3.20
RUN apk add --no-cache bash postgresql16-client age curl tzdata tar gzip rclone
COPY backup.sh alert.sh entrypoint.sh /backup/
RUN chmod +x /backup/*.sh
ENV TZ=America/Sao_Paulo
ENTRYPOINT ["/backup/entrypoint.sh"]
