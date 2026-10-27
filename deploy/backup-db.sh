#!/bin/bash
# Ежедневная копия базы и фото блюд. Хранятся 14 дней в /home/muslim/backups.
# Запускается сама каждую ночь (cron), вручную: bash /home/muslim/app/deploy/backup-db.sh
set -e                                             # любая ошибка — остановиться

APP=/home/muslim/app                               # где лежит проект
DEST=/home/muslim/backups                          # куда складываем копии
STAMP=$(date +%Y-%m-%d_%H-%M)                      # дата и время в имени файла
mkdir -p "$DEST"

# Копия базы «на ходу»: sqlite сам делает целую копию, даже если сайт в это время пишет заказы
"$APP/venv/bin/python" - "$APP/db.sqlite3" "$DEST/db-$STAMP.sqlite3" <<'PY'
import sqlite3, sys
source = sqlite3.connect(sys.argv[1])
target = sqlite3.connect(sys.argv[2])
with target:
    source.backup(target)
target.close()
source.close()
PY
gzip "$DEST/db-$STAMP.sqlite3"                     # сжимаем

# Фото блюд (папка media) — одним архивом
if [ -d "$APP/media" ]; then
    tar -czf "$DEST/media-$STAMP.tar.gz" -C "$APP" media
fi

# Старше 14 дней — удаляем
find "$DEST" -name 'db-*.sqlite3.gz' -mtime +14 -delete
find "$DEST" -name 'media-*.tar.gz' -mtime +14 -delete
echo "Копия готова: $DEST (db-$STAMP.sqlite3.gz)"