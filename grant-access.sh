#!/usr/bin/env bash
# Grant (or revoke) deploy access to this droplet for one person.
#
#   sudo ./grant-access.sh dan 'ssh-ed25519 AAAA... dan@example.org' msm-mobi
#   sudo ./grant-access.sh dan 'ssh-ed25519 AAAA...' msm-mobi dash
#   sudo ./grant-access.sh dan 'ssh-ed25519 AAAA...' all
#   sudo ./grant-access.sh --studies dan msm-mobi dash   # re-scope, no key
#   sudo ./grant-access.sh --revoke dan
#
# Creates the account from their public key, gives it the docker group and a
# share of this checkout, makes only the named studies' .env files readable to
# them, then verifies the result by running the real commands as that user --
# including checking that the studies you did NOT name stay unreadable.
# Idempotent: re-running it changes nothing and just re-reports the checks,
# and re-running with a different study list moves the .env modes to match.
# --studies does only that part, for someone who already has access: their
# account and key are untouched, so you do not have to go fishing their public
# key back out of a 700 home directory to change which studies they can read.
#
# READ THIS BEFORE GRANTING. Deploy access is data access, and the study list
# narrows only the accidental path, not the deliberate one. The docker group
# is root-equivalent: a member can `docker run -v dash_data:/d alpine cat
# /d/study.db`, or `docker compose exec dash printenv`, and get a study you
# did not name here. File modes do not constrain them. What the list buys is
# that a `grep -r` or a stray `cat */.env` across the checkout no longer
# sweeps up every study's secrets -- which is the mistake that actually
# happens. If the requirement is that they genuinely cannot reach another
# study's data, do not put them in the docker group at all; see Narrowing
# further than this script can in README.md.
#
# The checkout itself is shared whole, and cannot be narrowed per study: a
# single Git working tree needs write access across all of it to pull. The
# source is public on GitHub anyway. The .env files are the secrets.
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
	# What to rotate depends on what they were granted, but the docker group
	# means the honest answer is "assume everything on the box". The record
	# says what they could read without trying.
	RECORD="${STACK_DIR}/.access/${USER_NAME}"
	if [ -f "${RECORD}" ]; then
		say "They were granted: $(tr '\n' ' ' < "${RECORD}")"
		rm -f "${RECORD}"
	fi
	say ""
	say "Rotate ADMIN_TOKEN and the vendor API keys for those studies if the"
	say "parting is not amicable. And note that the docker group they just lost"
	say "was root-equivalent while they had it, so a deliberate reader could"
	say "have reached every study, not only the granted ones; if that matters"
	say "here, treat every secret on the box as exposed."
	say "PHONE_HASH_SALT cannot be rotated -- see dash/README.md."
	exit 0
fi

# --- grant ----------------------------------------------------------------

# --studies re-scopes an existing grant and takes no key.
SCOPE_ONLY=""
if [ "${1:-}" = "--studies" ]; then
	SCOPE_ONLY=1
	shift
	USER_NAME="${1:-}"
	PUBKEY="-"            # unused; the account already exists
	shift 1 2>/dev/null || true
else
	USER_NAME="${1:-}"
	PUBKEY="${2:-}"
	shift 2 2>/dev/null || true
fi

# Every study directory, meaning every directory holding a Dockerfile. Derived
# rather than listed so a new study needs no edit here.
ALL_STUDIES=()
for d in "${STACK_DIR}"/*/Dockerfile; do
	[ -e "${d}" ] || continue
	ALL_STUDIES+=("$(basename "$(dirname "${d}")")")
done

if [ -z "${USER_NAME}" ] || [ -z "${PUBKEY}" ] || [ "$#" -eq 0 ]; then
	say "usage: sudo $0 USER 'ssh-ed25519 AAAA... comment' STUDY [STUDY...]"
	say "       sudo $0 --studies USER STUDY [STUDY...]"
	say "       sudo $0 --revoke USER"
	say ""
	say "Studies on this host: ${ALL_STUDIES[*]:-none found}"
	say "Name only the ones they need, or 'all'. The list is required because"
	say "which studies' secrets a person can read is a decision, not a default."
	exit 1
fi

# --studies changes an existing grant, so refuse if there is none to change:
# silently creating nothing, or half-granting an account with no groups, would
# both be worse than saying so.
if [ -n "${SCOPE_ONLY}" ]; then
	if ! id -u "${USER_NAME}" >/dev/null 2>&1; then
		say "No such user: ${USER_NAME}"
		say "To grant access for the first time, pass their public key instead:"
		say "    sudo $0 ${USER_NAME} 'ssh-ed25519 AAAA... comment' $*"
		exit 1
	fi
	if ! id -nG "${USER_NAME}" | tr ' ' '\n' | grep -qx "${GROUP}"; then
		say "${USER_NAME} exists but is not in the ${GROUP} group, so they have"
		say "no access to re-scope. Grant it with their public key:"
		say "    sudo $0 ${USER_NAME} 'ssh-ed25519 AAAA... comment' $*"
		exit 1
	fi
fi

# Requested studies, validated against what exists. A typo must not silently
# grant nothing (or everything).
if [ "${#ALL_STUDIES[@]}" -eq 0 ]; then
	say "No study directories found in ${STACK_DIR}; is this the right checkout?"
	exit 1
fi
if [ "$1" = "all" ]; then
	STUDIES=("${ALL_STUDIES[@]}")
else
	STUDIES=()
	for requested in "$@"; do
		found=0
		for existing in "${ALL_STUDIES[@]}"; do
			[ "${requested}" = "${existing}" ] && found=1 && break
		done
		if [ "${found}" -eq 0 ]; then
			say "No such study: ${requested}"
			say "Studies on this host: ${ALL_STUDIES[*]:-none found}"
			say "Nothing was changed."
			exit 1
		fi
		STUDIES+=("${requested}")
	done
fi

# Is $1 in the granted list?
granted() {
	local name="$1" s
	for s in "${STUDIES[@]}"; do
		[ "${s}" = "${name}" ] && return 0
	done
	return 1
}

# Validate the key before creating anything. A public key pasted through a
# chat client or an editor arrives wrapped across lines or with the comment
# mangled more often than not, and a half-written authorized_keys is a
# confusing thing to debug later.
if [ -z "${SCOPE_ONLY}" ]; then
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
else
	FINGERPRINT="unchanged (--studies does not touch the key)"
fi

OWNER="$(stat -c %U "${STACK_DIR}")"
OWNER_HOME="$(getent passwd "${OWNER}" | cut -d: -f6)"

if [ -n "${SCOPE_ONLY}" ]; then
	say "Re-scoping ${USER_NAME} to: ${STUDIES[*]}"
	say "  was        $(tr '\n' ' ' < "${STACK_DIR}/.access/${USER_NAME}" 2>/dev/null || echo 'no record on file')"
else
	say "Granting deploy access to ${USER_NAME}"
	say "  key        ${FINGERPRINT}"
fi
say "  checkout   ${STACK_DIR} (owned by ${OWNER})"
say "  studies    ${STUDIES[*]}"

if [ -z "${SCOPE_ONLY}" ]; then

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

fi   # end of what --studies skips: key, account, groups, checkout

step "Studies"

# Compose needs to read the .env of a study they deploy, so those go to 640.
# The rest are forced back to 600 on every run, so re-running with a shorter
# study list actually takes access away instead of only adding it.
for env_file in "${STACK_DIR}"/*/.env; do
	[ -e "${env_file}" ] || continue
	study="$(basename "$(dirname "${env_file}")")"
	if granted "${study}"; then
		chmod 640 "${env_file}"
		ok "${study}/.env is group-readable (Compose needs it)"
	else
		chown "${OWNER}" "${env_file}"
		chmod 600 "${env_file}"
		ok "${study}/.env left at 600 (not granted)"
	fi
done

# Git needs no reconfiguring to change someone's study list.
if [ -z "${SCOPE_ONLY}" ]; then

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

fi   # end of the Git step

step "Record"
# Who has access to what is otherwise only inferable from /etc/group plus the
# .env modes, which is no way to answer the question months later or to brief
# whoever takes this over. Not committed: see .gitignore.
install -d -m 750 -o "${OWNER}" -g "${GROUP}" "${STACK_DIR}/.access"
printf '%s\n' "${STUDIES[@]}" > "${STACK_DIR}/.access/${USER_NAME}"
chmod 640 "${STACK_DIR}/.access/${USER_NAME}"
ok "recorded in .access/${USER_NAME}: ${STUDIES[*]}"

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
# Both directions are checked. An ungranted .env that is readable is the
# failure this study list exists to prevent, so it is a FAIL, not a note.
for env_file in "${STACK_DIR}"/*/.env; do
	[ -e "${env_file}" ] || continue
	study="$(basename "$(dirname "${env_file}")")"
	if granted "${study}"; then
		as_them "head -c1 '${env_file}'" \
			&& ok "can read ${study}/.env" \
			|| bad "cannot read ${study}/.env"
	else
		as_them "head -c1 '${env_file}'" \
			&& bad "can read ${study}/.env, which was not granted" \
			|| ok "cannot read ${study}/.env (not granted)"
	fi
done

# --- report ---------------------------------------------------------------

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [ "${FAILED}" -ne 0 ]; then
	step "Some checks failed. Fix those before telling ${USER_NAME} anything."
	exit 1
fi

# A re-scope needs no handover text: they already have the access and the
# instructions. Say what changed and stop.
if [ -n "${SCOPE_ONLY}" ]; then
	step "All checks passed. ${USER_NAME} can now read: ${STUDIES[*]}"
	say ""
	say "Their account, key and groups were not touched, so nothing has to be"
	say "sent to them. A study removed here takes effect immediately; one added"
	say "is readable from their next command."
	exit 0
fi

# Pad the comments to a fixed column, since the service name is interpolated
# and a ragged block is the kind of thing people assume they mis-pasted.
step "All checks passed. Send ${USER_NAME} this:"
cat <<REPORT

    ssh ${USER_NAME}@${IP:-<droplet ip>}
    cd ${STACK_DIR}
    git pull
    docker compose up -d --build ${STUDIES[0]}
$(printf '    %-40s %s\n' "docker compose ps" '# should reach "healthy" in ~40s')
$(printf '    %-40s %s\n' "docker compose logs -f ${STUDIES[0]}" '# Ctrl-C stops following')

  Yours: ${STUDIES[*]}
  Also on this host: $(cd "${STACK_DIR}" && docker compose config --services 2>/dev/null | tr '\n' ' ')

  Always name your own service. A bare 'docker compose up -d' restarts every
  study on the droplet, including other people's live ones. Never
  'docker compose down -v', which deletes the data volumes -- that is the
  participant databases. Participants mid-session survive a rebuild but meet
  new wording from their next turn, so deploy between recruitment batches.

  Changes go through GitHub, not this checkout: edit on your own machine,
  push, then 'git pull' here. The checkout is shared, so edits made in place
  collide and leave it ambiguous what is actually deployed.

REPORT

# Printed unconditionally: /etc/group now lists the membership, but the shell
# that ran this script was given its groups at login and cannot pick it up.
say "One thing for you: log out and back in. Your own ${GROUP} membership is"
say "not active in this session, so new files you create here will carry the"
say "wrong group until you reconnect."
