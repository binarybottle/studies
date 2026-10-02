#!/bin/sh
# The login banner for this droplet, shown to every user on every SSH login.
#
# Installed as /etc/update-motd.d/99-studies -- see Login banner in README.md.
# Ubuntu runs the scripts in that directory in lexical order and prints the
# output, so 99 puts this last: directly above the prompt, where it is read,
# rather than scrolled off the top by the default header and update notices.
#
# The point of it is the two commands that can lose participant data. A
# hostname is glanced at; this is in the way. It is aimed at someone who has
# deploy access, has four terminals open, and is about to paste something.
#
# The study list is derived from Docker's own labels rather than written here,
# so it stays true as studies are added and retired and this file never goes
# stale. Keep it quick -- it runs before every prompt -- and never let it fail
# a login: no set -e, and every lookup degrades to saying nothing.

printf '\n'
printf '  This droplet runs live studies with real participants.\n'
printf '  ----------------------------------------------------------------\n'

# One docker call, not one per study. A stopped container is a retired or
# paused study and is worth seeing: its data is still here.
STUDIES="$(
	timeout 5 docker ps -a \
		--filter label=com.docker.compose.project=studies \
		--format '{{.Label "com.docker.compose.service"}} {{.State}}' \
		2>/dev/null | grep -v '^caddy ' | sort
)"

if [ -n "${STUDIES}" ]; then
	printf '%s\n' "${STUDIES}" | while read -r svc state; do
		case "${state}" in
			running) printf '  %-12s live\n' "${svc}" ;;
			exited|created) printf '  %-12s stopped -- data still on the box\n' "${svc}" ;;
			*) printf '  %-12s %s\n' "${svc}" "${state}" ;;
		esac
	done
else
	# Docker not up, or not readable by this user. Say so rather than implying
	# the box is empty, which would be the dangerous reading.
	printf '  (could not read the study list -- do not assume the box is idle)\n'
fi

cat <<'TEXT'
  ----------------------------------------------------------------
  docker compose up -d --build <service>   always name your service
  docker compose down -v                   never: it deletes the
                                           participant databases

  A bare `up -d` restarts every study above, including other
  people's. Deploy between recruitment batches, not during one.
  Changes go through GitHub: edit locally, push, pull here.

  ~/studies/README.md             the stack
  ~/studies/<study>/README.md     one study
  ~/studies/capacity.sh           memory per study, and headroom

TEXT
