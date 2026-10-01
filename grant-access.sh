#!/usr/bin/env bash
# Grant (or revoke) deploy access to this droplet for one person.
#
#   sudo ./grant-access.sh dan 'ssh-ed25519 AAAA... dan@example.org'
#   sudo ./grant-access.sh --revoke dan
#
# Creates the account from their public key, gives it the docker group and a
# share of this checkout, then verifies the result by running the real
# commands as that user. Idempotent: re-running it for someone who already
# has access changes nothing and just re-reports the checks.
#
# READ THIS BEFORE GRANTING. Deploy access is data access, and cannot be
# narrowed. The docker group is root-equivalent, so the person can mount any
# volume and read every study's database, not only the one they came for. And
# Compose reads each study's .env as whoever invokes it, so they can read
# every API key and admin token on the box. See the Access section of
# README.md.
#
# Everything it does is derived from where this script lives, so the checkout
# can move without editing anything here.

set -euo pipefail

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GROUP=studies
FAILED=0

say()  { printf '%s\n' "$*"; }
step() { printf '\n%s\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; FAILED=1; }

if [ "$(id -u)" -ne 0 ]; then
	say "Run this with sudo: sudo $0 ..."
	exit 1
fi

# --- revoke ---------------------------------------------------------------

if [ "${1:-}" = "--revoke" ]; then
	USER_NAME="${2:-}"
	[ -n "${USER_NAME}" ] || { say "usage: sudo $0 --revoke USER"; exit 1; }
	id -u "${USER_NAME}" >/dev/null 2>&1 || { say "No such user: ${USER_NAME}"; exit 1; }

	# Removing the groups is what actually revokes deploy ability; the account
	# is left in place because deleting a home directory is a separate
	# decision, and an account with no groups can do nothing here anyway.
	gpasswd -d "${USER_NAME}" docker 2>/dev/null || true
	gpasswd -d "${USER_NAME}" "${GROUP}" 2>/dev/null || true
	say "Removed ${USER_NAME} from the docker and ${GROUP} groups."
	say "Their next login still succeeds but can neither read the checkout nor reach Docker."
	say ""
	say "To remove the account and its home as well:"
	say "    sudo deluser --remove-home ${USER_NAME}"
	say ""
	say "They have had read access to every secret in every .env. Rotate"
	say "ADMIN_TOKEN and the vendor API keys if the parting is not amicable."
	say "PHONE_HASH_SALT cannot be rotated -- see dash/README.md."
	exit 0
fi

# --- grant ----------------------------------------------------------------

USER_NAME="${1:-}"
PUBKEY="${2:-}"
if [ -z "${USER_NAME}" ] || [ -z "${PUBKEY}" ]; then
	say "usage: sudo $0 USER 'ssh-ed25519 AAAA... comment'"
	say "       sudo $0 --revoke USER"
	exit 1
fi

# Validate the key before creating anything. A public key pasted through a
# chat client or an editor arrives wrapped across lines or with the comment
# mangled more often than not, and a half-written authorized_keys is a
# confusing thing to debug later.
KEYFILE="$(mktemp)"
trap 'rm -f "${KEYFILE}"' EXIT
printf '%s\n' "${PUBKEY}" > "${KEYFILE}"
if ! FINGERPRINT="$(ssh-keygen -l -f "${KEYFILE}" 2>&1)"; then
	say "That does not parse as an SSH public key, so nothing was changed:"
	say "    ${FINGERPRINT}"
	say ""
	say "Expected one line, e.g. ssh-ed25519 AAAAC3Nza... name@host -- the"
	say "contents of their ~/.ssh/id_ed25519.pub, quoted."
	exit 1
fi

OWNER="$(stat -c %U "${STACK_DIR}")"
OWNER_HOME="$(getent passwd "${OWNER}" | cut -d: -f6)"

say "Granting deploy access to ${USER_NAME}"
say "  key        ${FINGERPRINT}"
say "  checkout   ${STACK_DIR} (owned by ${OWNER})"

step "Account"
if id -u "${USER_NAME}" >/dev/null 2>&1; then
	ok "${USER_NAME} already exists"
else
	adduser --disabled-password --gecos "" "${USER_NAME}" >/dev/null
	ok "created ${USER_NAME}, no password (key-only login)"
fi

AUTH="/home/${USER_NAME}/.ssh/authorized_keys"
install -d -m 700 -o "${USER_NAME}" -g "${USER_NAME}" "/home/${USER_NAME}/.ssh"
if [ -f "${AUTH}" ] && grep -qxF "${PUBKEY}" "${AUTH}"; then
	ok "key already present in authorized_keys"
else
	printf '%s\n' "${PUBKEY}" >> "${AUTH}"
	ok "appended key to ${AUTH}"
fi
chown "${USER_NAME}:${USER_NAME}" "${AUTH}"
chmod 600 "${AUTH}"

step "Groups"
usermod -aG docker "${USER_NAME}"
ok "${USER_NAME} is in docker (root-equivalent on this host)"
groupadd -f "${GROUP}"
usermod -aG "${GROUP}" "${USER_NAME}"
usermod -aG "${GROUP}" "${OWNER}"
ok "${USER_NAME} and ${OWNER} are both in ${GROUP}"

step "Shared checkout"
# Traverse-only on the owner's home: the group can reach the checkout by
# path but cannot list the rest of the home directory, and ~/.ssh keeps its
# own 700 regardless.
chgrp "${GROUP}" "${OWNER_HOME}"
chmod g=x,o= "${OWNER_HOME}"
ok "${OWNER_HOME} is traversable by ${GROUP}, not listable"

chgrp -R "${GROUP}" "${STACK_DIR}"
chmod -R g+rwX "${STACK_DIR}"
# The setgid bit is what makes files created later inherit the group. Without
# it the sharing decays the first time either person adds a file.
find "${STACK_DIR}" -type d -exec chmod g+s {} +
ok "${STACK_DIR} is group-writable, with setgid on directories"

for env_file in "${STACK_DIR}"/*/.env; do
	[ -e "${env_file}" ] || continue
	chmod 640 "${env_file}"
	ok "$(basename "$(dirname "${env_file}")")/.env is group-readable (Compose needs it)"
done

step "Git"
git -C "${STACK_DIR}" config core.sharedRepository group
ok "core.sharedRepository=group, so Git creates group-writable objects"
# This repository is public, so HTTPS needs no key and no deploy key has to
# be shared around.
if git -C "${STACK_DIR}" remote get-url origin | grep -q '^git@'; then
	HTTPS_URL="$(git -C "${STACK_DIR}" remote get-url origin | sed -e 's#^git@github.com:#https://github.com/#')"
	git -C "${STACK_DIR}" remote set-url origin "${HTTPS_URL}"
	ok "origin switched to ${HTTPS_URL}"
else
	ok "origin already pulls without a key: $(git -C "${STACK_DIR}" remote get-url origin)"
fi
# Git refuses a repository owned by another user unless told it is expected.
# Set system-wide so nobody has to configure anything on first login.
git config --system --add safe.directory "${STACK_DIR}" 2>/dev/null || true
git config --system --get-all safe.directory | grep -qxF "${STACK_DIR}" \
	&& ok "safe.directory set system-wide (no per-user setup needed)" \
	|| bad "could not set safe.directory system-wide"

# --- verify, as them ------------------------------------------------------
#
# sudo -u applies the full group list through initgroups, so this exercises
# the membership granted a moment ago rather than a cached session.

step "Verifying as ${USER_NAME}"

as_them() { sudo -u "${USER_NAME}" -H bash -c "$1" >/dev/null 2>&1; }

for g in docker "${GROUP}"; do
	id -nG "${USER_NAME}" | tr ' ' '\n' | grep -qx "${g}" \
		&& ok "group ${g}" || bad "group ${g} missing"
done

as_them "cd '${STACK_DIR}'" \
	&& ok "can reach the checkout" || bad "cannot reach the checkout"
as_them "cd '${STACK_DIR}' && touch .access-test && rm .access-test" \
	&& ok "can write to the checkout" || bad "cannot write to the checkout"
as_them "cd '${STACK_DIR}' && git fetch --dry-run" \
	&& ok "can fetch from GitHub" || bad "cannot fetch from GitHub"
as_them "cd '${STACK_DIR}' && docker compose ps" \
	&& ok "can run docker compose" || bad "cannot run docker compose"
for env_file in "${STACK_DIR}"/*/.env; do
	[ -e "${env_file}" ] || continue
	as_them "head -c1 '${env_file}'" \
		&& ok "can read $(basename "$(dirname "${env_file}")")/.env" \
		|| bad "cannot read $(basename "$(dirname "${env_file}")")/.env"
done

# --- report ---------------------------------------------------------------

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [ "${FAILED}" -ne 0 ]; then
	step "Some checks failed. Fix those before telling ${USER_NAME} anything."
	exit 1
fi

step "All checks passed. Send ${USER_NAME} this:"
cat <<REPORT

    ssh ${USER_NAME}@${IP:-<droplet ip>}
    cd ${STACK_DIR}
    git pull
    docker compose up -d --build <service>   # name the service, always
    docker compose ps                        # should reach "healthy" in ~40s
    docker compose logs -f <service>          # Ctrl-C stops following

  Services on this host: $(cd "${STACK_DIR}" && docker compose config --services 2>/dev/null | tr '\n' ' ')

  A bare 'docker compose up -d' restarts every study on the droplet, so
  always name one. Never 'docker compose down -v', which deletes the data
  volumes. Participants mid-session survive a rebuild but meet new wording
  from their next turn, so deploy between recruitment batches.

REPORT

# Printed unconditionally: /etc/group now lists the membership, but the shell
# that ran this script was given its groups at login and cannot pick it up.
say "One thing for you: log out and back in. Your own ${GROUP} membership is"
say "not active in this session, so new files you create here will carry the"
say "wrong group until you reconnect."
