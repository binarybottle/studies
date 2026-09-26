#!/usr/bin/env bash
# Download the study's exports to a dated folder on this machine.
#
#   msm-mobi/scripts/download.sh                 # -> ~/Desktop/msm-mobi-<date>/
#   msm-mobi/scripts/download.sh ~/data/msm      # -> ~/data/msm/<date>/
#
# Needs: ssh access to the droplet (to read the admin token from the running
# container) and an IP on the Caddyfile allow-list for /admin/*. The token
# is read from the container rather than the .env file so that an inline
# comment or stray whitespace in .env cannot corrupt it.

set -euo pipefail

HOST="${MSM_HOST:-https://msm-mobi.study.childmind.org}"
DROPLET="${MSM_DROPLET:-arno@167.71.248.46}"
BASE="${1:-$HOME/Desktop/msm-mobi}"
OUT="${BASE}/$(date +%F)"

TOKEN=$(ssh "${DROPLET}" 'cd ~/studies && docker compose exec -T msm-mobi printenv ADMIN_TOKEN' \
	| /usr/bin/tr -d ' \t\r\n')
if [ "${#TOKEN}" -lt 20 ]; then
	echo "Could not read ADMIN_TOKEN from the container (got ${#TOKEN} characters). Is ssh working?" >&2
	exit 1
fi

mkdir -p "${OUT}"
for name in blocks participants quality; do
	curl -sf "${HOST}/admin/${name}.csv?token=${TOKEN}" -o "${OUT}/${name}.csv" || {
		echo "Download of ${name}.csv failed: wrong token, or this IP is not on the Caddyfile allow-list." >&2
		exit 1
	}
	# A rejected request answers 404 with a JSON body; -f above turns that
	# into a failure, but check the header too in case of a proxy page.
	head -1 "${OUT}/${name}.csv" | grep -q ',' || {
		echo "${name}.csv does not look like a CSV: $(head -c 80 "${OUT}/${name}.csv")" >&2
		exit 1
	}
done

echo "Downloaded to ${OUT}:"
for name in blocks participants quality; do
	printf '  %-17s %5d rows\n' "${name}.csv" "$(($(wc -l < "${OUT}/${name}.csv") - 1))"
done
echo
echo "Next: python3 $(dirname "$0")/screen.py ${OUT}/quality.csv --blocks ${OUT}/blocks.csv --show"
