FROM alpine:3.20
# rclone fica para depois (envio ao Drive opcional); instalar aqui quando for ativado
RUN apk add --no-cache bash postgresql16-client age curl tzdata tar gzip
COPY backup.sh alert.sh entrypoint.sh /backup/
RUN chmod +x /backup/*.sh
ENV TZ=America/Sao_Paulo
ENTRYPOINT ["/backup/entrypoint.sh"]
