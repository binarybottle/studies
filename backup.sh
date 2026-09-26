#!/usr/bin/env bash
# Nightly backup of every study's database.
#
# Each study keeps its participant data in a study.db on its own volume. For
# DASH that file is the only key connecting Retell transcripts to Prolific
# submissions; for MSM-MoBI it is the data itself. Losing either is
# unrecoverable, so this runs unattended and keeps 30 days of history.
#
# `sqlite3 .backup` is used rather than `cp` because SQLite runs in WAL mode:
# a plain copy taken mid-write produces a torn file that may not restore.
#
# Install:
#   chmod +x ~/studies/backup.sh
#   crontab -e
#   0 3 * * * /home/arno/studies/backup.sh >> /home/arno/studies/backup.log 2>&1
#
# Restore (substitute the study's service and volume):
#   docker compose stop dash
#   docker run --rm -v studies_dash_data:/data -v ~/studies/backups:/b \
#       alpine cp /b/dash-2026-08-20.db /data/study.db
#   docker compose start dash

set -euo pipefail

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${STACK_DIR}/backups"
STAMP="$(date +%F)"
KEEP_DAYS=30

# One entry per study: the compose service name. Each keeps its database at
# /data/study.db and has a participants table to count.
SERVICES=(dash msm-mobi)

mkdir -p "${BACKUP_DIR}"

backup_one() {
	local service="$1"
	local out="${BACKUP_DIR}/${service}-${STAMP}.db"

	# Skip a study that is not running rather than failing the whole job.
	if ! docker compose -f "${STACK_DIR}/compose.yml" ps --status running --services | grep -qx "${service}"; then
		echo "$(date -Is) ${service}: not running, skipped"
		return 0
	fi

	# Run the backup inside the container so the same SQLite build that wrote
	# the database is the one reading it.
	docker compose -f "${STACK_DIR}/compose.yml" exec -T "${service}" \
		python -c "
import sqlite3
source = sqlite3.connect('/data/study.db')
target = sqlite3.connect('/data/backup-tmp.db')
with target:
    source.backup(target)
target.close(); source.close()
"

	docker compose -f "${STACK_DIR}/compose.yml" cp \
		"${service}:/data/backup-tmp.db" "${out}"

	docker compose -f "${STACK_DIR}/compose.yml" exec -T "${service}" \
		python -c "import os; os.remove('/data/backup-tmp.db')"

	# Verify the copy opens and contains the participants table before trusting it.
	python3 - "${out}" <<'PY'
import sqlite3, sys
path = sys.argv[1]
connection = sqlite3.connect(path)
count = connection.execute("SELECT COUNT(*) FROM participants").fetchone()[0]
print(f"{path}: {count} participants")
PY

	echo "$(date -Is) backup complete: $(basename "${out}")"
}

for service in "${SERVICES[@]}"; do
	backup_one "${service}"
done

# Older backups of dash were named study-<date>.db; prune those too.
find "${BACKUP_DIR}" \( -name 'study-*.db' -o -name '*-????-??-??.db' \) -mtime "+${KEEP_DAYS}" -delete
