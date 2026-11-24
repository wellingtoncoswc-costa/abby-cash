# Restauração de backup (testar em banco descartável)

Os arquivos ficam no volume `abby-cash_backups` (`daily/`, `weekly/`, `monthly/`), criptografados com `age`.
**Mantenha uma cópia fora do servidor** (`BACKUP_RCLONE_REMOTE`, ver `infra/deploy.md`): é fortemente recomendada e obrigatória antes de confiar nestes backups.
A chave **privada** (gerada com `age-keygen`) fica só com o dono.

```bash
# 1. copiar os arquivos mais recentes para uma pasta de trabalho
docker run --rm -v abby-cash_backups:/b -v "$PWD/restore:/out" alpine sh -c 'cp /b/daily/* /out/'
cd restore && ls -1t abby-db-*.age abby-files-*.age | head
# 2. descriptografar (chave privada do dono, ex.: ~/abby-backup.key)
age -d -i ~/abby-backup.key abby-db-<ts>.dump.age > db.dump
age -d -i ~/abby-backup.key abby-files-<ts>.tar.gz.age > files.tar.gz
# 3. banco descartável (NUNCA o de produção)
docker run -d --name abby-restore-test -e POSTGRES_PASSWORD=x -e POSTGRES_DB=abby postgres:16.6
sleep 5
docker exec -i abby-restore-test pg_restore -U postgres -d abby --no-owner --role=postgres < db.dump
# 4. verificações
docker exec abby-restore-test psql -U postgres -d abby -c "select count(*) from users;"
docker exec abby-restore-test psql -U postgres -d abby -c "select count(*) from transactions;"
docker exec abby-restore-test psql -U postgres -d abby -c "select version_num from alembic_version;"   # = head atual
docker exec abby-restore-test psql -U postgres -d abby -c \
  "select count(*) from transactions where amount_cents is null;"                                         # deve ser 0
mkdir files && tar -xzf files.tar.gz -C files && find files -type f | wc -l                              # anexos presentes
# 5. limpeza
docker rm -f abby-restore-test && rm -rf restore
```

Restauração real: parar `api`/`worker`, restaurar no volume do Postgres de produção só com o dono presente, subir de novo
(as migrações rodam no start). Testar a restauração pelo menos uma vez antes de confiar no backup, e a cada trimestre.
