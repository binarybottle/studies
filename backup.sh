#!/usr/bin/env bash
# Nightly backup of the study linkage database.
#
# study.db is the only key connecting Retell transcripts to Prolific
# submissions. Losing it makes every transcript permanently unattributable, so
# this runs unattended and keeps 30 days of history.
#
# `sqlite3 .backup` is used rather than `cp` because SQLite runs in WAL mode:
# a plain copy taken mid-write produces a torn file that may not restore.
#
# Install:
#   chmod +x ~/studies/backup.sh
#   crontab -e
#   0 3 * * * /home/arno/studies/backup.sh >> /home/arno/studies/backup.log 2>&1
#
# Restore:
#   docker compose stop dash
#   docker run --rm -v studies_dash_data:/data -v ~/studies/backups:/b \
#       alpine cp /b/study-2026-08-20.db /data/study.db
#   docker compose start dash

set -euo pipefail

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${STACK_DIR}/backups"
STAMP="$(date +%F)"
KEEP_DAYS=30

mkdir -p "${BACKUP_DIR}"

# Run the backup inside the container so the same SQLite build that wrote the
# database is the one reading it.
docker compose -f "${STACK_DIR}/compose.yml" exec -T dash \
	python -c "
import sqlite3, sys
source = sqlite3.connect('/data/study.db')
target = sqlite3.connect('/data/backup-tmp.db')
with target:
    source.backup(target)
target.close(); source.close()
"

docker compose -f "${STACK_DIR}/compose.yml" cp \
	"dash:/data/backup-tmp.db" "${BACKUP_DIR}/study-${STAMP}.db"

docker compose -f "${STACK_DIR}/compose.yml" exec -T dash \
	python -c "import os; os.remove('/data/backup-tmp.db')"

# Verify the copy opens and contains the participants table before trusting it.
python3 - "${BACKUP_DIR}/study-${STAMP}.db" <<'PY'
import sqlite3, sys
path = sys.argv[1]
connection = sqlite3.connect(path)
count = connection.execute(
    "SELECT COUNT(*) FROM participants"
).fetchone()[0]
print(f"{path}: {count} participants")
PY

find "${BACKUP_DIR}" -name 'study-*.db' -mtime "+${KEEP_DAYS}" -delete

echo "$(date -Is) backup complete: study-${STAMP}.db"
