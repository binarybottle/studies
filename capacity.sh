#!/usr/bin/env bash
# What each study is using against its own ceiling, and what the box has left.
#
#   ./capacity.sh          # once, now
#   ./capacity.sh --watch  # every 10s until Ctrl-C
#
# Run this during a live batch, not an idle afternoon: the numbers only mean
# something under load. It is the answer to "is 768 MB still the right cap for
# msm-mobi" and to "can this droplet take another study".
#
# Why a script rather than a budget written down in the README: the services
# come from `docker compose config --services`, so a study added or retired
# changes nothing here. There is no list to maintain and no total to rebalance.
#
# Remember that mem_limit is a ceiling, not a reservation. A study capped at
# 768 MB and using 250 MB is using 250 MB. So the caps are expected to sum to
# more than the droplet has, and that sum is not a number worth computing; the
# two that matter are each study against its own cap, and `available` for the
# host. They answer different questions and both are printed below.

set -uo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WARN_PCT=50   # flag a container using more than this share of its own ceiling

report() {
	local flagged=0 svc cid limit swap usage pct state

	printf '%-12s %-22s %7s  %s\n' STUDY MEMORY LIMIT% STATE
	printf '%-12s %-22s %7s  %s\n' ----- ------ ------ -----

	while read -r svc; do
		[ -n "${svc}" ] || continue
		cid="$(docker compose ps -q "${svc}" 2>/dev/null)"

		# A finished study is usually a stopped container, which is the point:
		# it holds no memory at all while keeping its volume and its data.
		if [ -z "${cid}" ]; then
			printf '%-12s %-22s %7s  %s\n' "${svc}" "-" "-" "stopped (no memory held)"
			continue
		fi

		read -r limit swap <<<"$(docker inspect -f '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}' "${cid}")"
		usage="$(docker stats --no-stream --format '{{.MemUsage}}' "${cid}" 2>/dev/null)"
		pct="$(docker stats --no-stream --format '{{.MemPerc}}' "${cid}" 2>/dev/null | tr -d '%')"

		if [ "${limit}" = "0" ]; then
			# Without a limit the percentage is of the whole host, which is a
			# different and much less useful number, so do not print it as if
			# it were headroom.
			printf '%-12s %-22s %7s  %s\n' "${svc}" "${usage%% /*}" "-" \
				"NO LIMIT -- add mem_limit in compose.yml"
			flagged=1
			continue
		fi

		state="ok"
		if awk "BEGIN{exit !(${pct:-0} > ${WARN_PCT})}"; then
			state="above ${WARN_PCT}% of its cap -- consider raising it"
			flagged=1
		fi
		# A limit without memswap_limit lets the container swap to twice the
		# cap instead of dying, which is the failure this is meant to avoid.
		if [ "${swap}" != "${limit}" ]; then
			state="${state}; memswap_limit != mem_limit (can swap past the cap)"
			flagged=1
		fi

		printf '%-12s %-22s %6s%%  %s\n' "${svc}" "${usage}" "${pct}" "${state}"
	done <<<"$(docker compose config --services 2>/dev/null)"

	# The host figure is the one that answers "room for another study". Use
	# `available`, not `free`: Linux spends idle memory on page cache, so
	# `free` reads alarmingly low on a healthy box and means nothing.
	echo
	free -m | awk '
		/^Mem:/   {printf "host    %5d MB total, %5d MB available\n", $2, $7}
		/^Swap:/  {printf "swap    %5d MB total, %5d MB used\n", $2, $3}'

	# Containers are capped with memswap_limit == mem_limit, so they cannot
	# swap. Swap in use therefore means the host itself is under pressure, or
	# a build is running.
	if [ "$(free -m | awk '/^Swap:/{print $3}')" -gt 100 ]; then
		echo
		echo "Swap is in use. Containers cannot swap, so this is the host:"
		echo "a build, or genuine pressure. Check before adding a study."
		flagged=1
	fi

	return "${flagged}"
}

if [ "${1:-}" = "--watch" ]; then
	while true; do
		clear
		date
		echo
		report || true
		sleep 10
	done
fi

report
