"""
foresight — predict the consequences of an action before it runs, and judge
whether it should.

This is the part that takes LeCun's complaint seriously inside the narrow
world Basilisk actually operates: a shell on one machine.  Basilisk can't model
physics, but it CAN model "what does this command do to this system, is it
reversible, how big is the blast radius, and does that match what the operator
seems to want."  The output enriches the confirmation card and can hard-block
catastrophes even in auto mode.

Two tiers:

  1. DETERMINISTIC rules (always on, free, instant).  Pattern-match the
     command against known-catastrophic and known-risky shapes.  These set a
     FLOOR: a rule-block cannot be argued down by the model.
  2. MODEL pass (optional).  If a completer is supplied, ask it to predict
     consequences as structured JSON.  It may ESCALATE a verdict (allow->
     caution, caution->block) but never DE-escalate below the rule floor.
     Fail-open on error (returns the rule verdict) so a flaky model never
     blocks legitimate work.

Verdict the host acts on:
    allow   — run normally (still subject to the operator's confirm gate)
    caution — run allowed, but the card shows the predicted consequences and
              undo hint; in auto-mode the host SHOULD still confirm these
    block   — refuse to run even in auto-mode; require an explicit override
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

# ── ONE AUTHORITY FOR "IS THIS CATASTROPHIC" ─────────────────────────
# basilisk_safety.is_catastrophic_command is the structural destructive floor:
# it shlex-tokenises, normalises $IFS, recurses into `sh -c` payloads and
# classifies by RESOLVED ARGV against the real system-directory sets.  This
# module used to re-answer the same question with a one-line regex, and a
# duplicate detector drifts from the original in both directions at once:
#
#   rm -rf node_modules/     safety: ok            foresight: BLOCK   (!)
#   rm -rf ./build           safety: ok            foresight: BLOCK   (!)
#   rm -rf dist/*            safety: ok            foresight: BLOCK   (!)
#   rm -rf ~/.cache/pip      safety: ok            foresight: BLOCK   (!)
#   find / -delete           safety: CATASTROPHIC  foresight: allow   (!)
#
# The regex asked "does an -rf appear, and is there a `/`, `~` or `*` ANYWHERE
# after it" — which every relative path in a project tree satisfies.  So the
# most routine cleanup command in software development was hard-BLOCKED, with
# no override, while `find / -delete` (no `rm` token at all) sailed past.
# Delegating fixes both columns and leaves one place to fix the next bypass.
#
# Imported defensively: foresight's contract is that it imports nothing from
# basilisk.py / basilisk_core.py / basilisk_persona.py.  basilisk_safety is
# none of those — it is the GTK-free, stdlib-only floor that basilisk_scope
# already builds on — but if it ever moves, the legacy regex below still runs
# as a fallback rather than leaving the floor open.
try:
    from basilisk_safety import is_catastrophic_command as _safety_catastrophic
except Exception:  # pragma: no cover - defensive
    _safety_catastrophic = None


PROMPT_BLOCK = (
    "FORESIGHT: before any state-changing command runs, its consequences are "
    "predicted and a verdict (allow/caution/block) is attached. Catastrophic, "
    "irreversible commands are blocked outright even in auto-mode and need an "
    "explicit override from the operator. When you propose a command, prefer "
    "the reversible form and name the undo path — it clears foresight faster."
)


# (compiled_pattern, reversibility, blast_radius, reason)
# Order matters: first match wins for the rule floor.
# The recursive-delete rule. Used ONLY when basilisk_safety could not be
# imported — see the note at the top of this file. It cannot tell
# `rm -rf node_modules/` from `rm -rf /`, which is why it is no longer the
# primary: it is a floor of last resort, better than nothing and worse than
# the structural check.
_CATASTROPHIC_RM_FALLBACK: List = [
    # Recursive AND force, in ANY flag arrangement: combined (-rf/-fr), split
    # (-r … -f), or long-form (--recursive … --force), in either order. The old
    # rule only caught the single combined token, so `rm -r -f /` and
    # `rm --recursive --force /` slipped the catastrophic floor entirely.
    (re.compile(
        r"\brm\b(?=[^\n]*(?:-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|"
        r"(?:-[a-zA-Z]*r\b|--recursive)[^\n]*(?:-[a-zA-Z]*f\b|--force)|"
        r"(?:-[a-zA-Z]*f\b|--force)[^\n]*(?:-[a-zA-Z]*r\b|--recursive)))"
        r"[^\n]*(/|~|\*|\$HOME)"),
     "irreversible", "user",
     "recursive force-delete of a broad path — data loss, no undo"),
]

# Recursive force-delete of a HOME DIRECTORY ROOT.
#
# This one is NOT redundant with the structural floor, and it is the reason
# delegating everything would have been wrong. basilisk_safety deliberately
# keeps `home` out of _CRITICAL_TOP so that `rm -rf /home/me/loot` — ordinary
# work — stays quiet, and it catches a bare `~` / `$HOME` separately. But
# `/home/user` spelled out in full is the same directory as `~`, and it fell
# between the two:
#
#   rm -rf ~              safety: CATASTROPHIC
#   rm -rf /home/user     safety: ok          <- every file the user owns
#
# So the home root is matched here, by the path SHAPE: /home/<name> or
# /Users/<name> (macOS) or /root, with nothing deeper after it. One more
# segment and it is a subdirectory again, which is work, not a wipe:
#
#   rm -rf /home/me/project   -> allow
#   rm -rf /home/me/.cache    -> allow
_CATASTROPHIC: List = [
    (re.compile(
        r"\brm\b(?=[^\n]*(?:-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|"
        r"(?:-[a-zA-Z]*r\b|--recursive)[^\n]*(?:-[a-zA-Z]*f\b|--force)|"
        r"(?:-[a-zA-Z]*f\b|--force)[^\n]*(?:-[a-zA-Z]*r\b|--recursive)))"
        r"[^\n]*\s(?:/(?:home|Users)/[^/\s'\"]+|/root)/?(?=[\s'\"]|$)"),
     "irreversible", "user",
     "recursive force-delete of a home directory ROOT — every file that user "
     "owns, no undo"),
    (re.compile(r"\b(mkfs|mke2fs|mkfs\.\w+)\b"),
     "irreversible", "system", "formats a filesystem — destroys all data on it"),
    (re.compile(r"\bdd\b.*\bof=/dev/(sd|nvme|mmcblk|loop)"),
     "irreversible", "system", "raw write to a block device — wipes the disk/partition"),
    (re.compile(r"\b(fdisk|sfdisk|parted|gdisk)\b.*?/dev/"),
     "irreversible", "system", "edits the partition table — can brick the boot/data layout"),
    (re.compile(r"\bfastboot\s+(flash|erase|format)\b"),
     "irreversible", "system",
     "flashes/erases a device partition — A/B slot or boot brick risk on the OnePlus 6"),
    (re.compile(r"(:\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:|fork\s*bomb)"),
     "irreversible", "system", "fork bomb — exhausts the process table, hangs the box"),
    (re.compile(r">\s*/dev/(sd|nvme|mmcblk)"),
     "irreversible", "system", "redirects output straight onto a block device"),
    (re.compile(r"\bchmod\s+-R\s+0*7{3}\s+/(?![a-zA-Z])"),
     "hard", "system", "recursive 777 from root — wrecks the permission model"),
]

_UNDO_HINTS = {
    "apt": "reinstall with: apt install <pkg>  (apt keeps removed-pkg lists in /var/log/apt/history.log)",
    "pacman": "reinstall with: sudo pacman -S <pkg>  (removed-pkg history is in /var/log/pacman.log; cached .pkg.tar.zst files under /var/cache/pacman/pkg let you reinstall the exact version offline)",
    "dnf": "reinstall with: sudo dnf install <pkg>  (undo the whole transaction with: sudo dnf history undo last)",
    "zypper": "reinstall with: sudo zypper install <pkg>  (roll the whole transaction back with: sudo zypper rollback, or a btrfs snapper snapshot if configured)",
    "rpm": "reinstall with: sudo rpm -i <pkg>.rpm, or via your package manager (rpm itself keeps no transaction history — dnf/zypper do)",
    "iptables": "rules are not saved unless you persisted them; reboot or reload your saved ruleset to restore",
    "ufw": "re-enable with: ufw enable  (and reload your rule profile)",
    "systemctl": "restart/enable the unit: systemctl enable --now <unit>",
    "git_reset": "recover via: git reflog  (reachable commits survive ~30 days)",
    "ip_link": "bring it back with: sudo ip link set <iface> up  (if this is the link you are on, you will need console/out-of-band access)",
}

# Each rule carries the KEY of its own undo hint (or None when the action has no
# honest undo — a hard kill loses unsaved state, an unaudited script has already
# run, a recursive chown has no generic inverse).
#
# The undo used to be looked up by scanning the whole command string for any
# tool name in _UNDO_HINTS and taking the first dict-order hit. That is the same
# defect twice over. It fired on names that were merely MENTIONED — `killall -9
# apt` and `chown -R apt:apt /srv/thing` were both offered "reinstall with: apt
# install <pkg>", and `git_reset` matched any command containing the letters
# g-i-t, including `rm -rf /var/log/digital-archive` and anything mentioning
# "legitimate". And it could not see the rule that actually fired, so dict order
# decided ties. A wrong undo is worse than none: it reads as "this is
# recoverable" at the exact moment the operator is deciding whether to let a
# risky command run. Tying the hint to the rule makes a mismatch unrepresentable
# — there is no string to re-scan and no order to depend on.
#
# COVERAGE, likewise, was one-sided: _UNDO_HINTS carried pacman and dnf entries,
# but the only package-removal RULE was apt's. So foresight cautioned on Debian
# and stayed silent on Arch, Fedora, openSUSE and raw rpm — `sudo pacman -Rdd
# glibc` came back a plain "allow". The hint table was the evidence of intent;
# the rule table just never caught up.
_RISKY: List = [
    (re.compile(r"\b(iptables|nft)\b.*(-F|flush)"),
     "hard", "network", "flushes firewall rules — drops your packet filtering",
     "iptables"),
    (re.compile(r"\bufw\s+(disable|reset)\b"),
     "hard", "network", "disables/resets the host firewall", "ufw"),
    (re.compile(r"\bsystemctl\s+(stop|disable|mask)\s+(ssh|sshd|NetworkManager|network)"),
     "reversible", "network",
     "stops/disables connectivity or remote access — lockout risk", "systemctl"),
    (re.compile(r"\bip\s+link\s+set\s+\w+\s+down\b"),
     "reversible", "network",
     "brings an interface down — you may lose the link you're on", "ip_link"),
    # COMMAND POSITION, NOT A BARE WORD ANYWHERE ON THE LINE.
    # `(?<![\w/])(passwd|…)` matched the WORD, so every command that merely
    # MENTIONED it was cautioned as an account change:
    #     grep -rn passwd ./src          -> caution "changes an account
    #     cat req.txt | grep passwd         credential/shell"
    # `/etc/passwd` was already excluded by the `/` lookbehind; the gap was the
    # bare token. Anchor to the start of the line or a shell operator, so it is
    # the command being RUN rather than a string being searched for.
    (re.compile(r"(?:^|[\n;&|]|&&|\|\||\bsudo\s+|\bdoas\s+)\s*"
                r"(passwd|usermod|chsh)\b"),
     "hard", "user", "changes an account credential/shell", None),
    (re.compile(r"\bapt(-get)?\s+(remove|purge|autoremove)\b"),
     "hard", "system", "removes packages — may pull dependencies with them",
     "apt"),
    (re.compile(r"\bpacman\s+(?:-[A-Za-z]*R|--remove)"),
     "hard", "system", "removes packages — may pull dependencies with them",
     "pacman"),
    (re.compile(r"\bpacman\s+(?:-[A-Za-z]*R[A-Za-z]*d{2}|--nodeps\s+--nodeps)"),
     "hard", "system",
     "removes packages while IGNORING dependencies — this is how a box loses "
     "glibc and stops booting", "pacman"),
    (re.compile(r"\b(dnf|yum|microdnf)\s+(remove|erase|autoremove)\b"),
     "hard", "system", "removes packages — may pull dependencies with them",
     "dnf"),
    (re.compile(r"\bzypper\b.*\b(remove|rm)\b"),
     "hard", "system", "removes packages — may pull dependencies with them",
     "zypper"),
    (re.compile(r"\brpm\s+(?:--erase\b|-[a-zA-Z]*e[a-zA-Z]*\b)"),
     "hard", "system",
     "removes a package with no transaction history to undo it", "rpm"),
    # ── GIT: ONLY THE FORM THAT CAN LOSE SOMEONE ELSE'S WORK ─────────
    # `git reset --hard`, `git clean -fd` and `git push --force-with-lease` are
    # a coding assistant's ordinary vocabulary — "drop my changes", "clear the
    # untracked junk", "update the branch I just rebased" — and cautioning all
    # three put a consequence card in front of the operator several times an
    # hour for work he had just asked for. Local history is recoverable from
    # the reflog for ~30 days, and --force-with-lease REFUSES to overwrite a
    # remote that moved, which is precisely the accident worth warning about.
    #
    # A bare `--force` / `-f` push is the one that is genuinely unrecoverable
    # and not only to the operator: it discards whatever the remote had, which
    # may be a colleague's commits, with no reflog on their side. That one
    # still cautions. (--force-if-includes is likewise lease-checked.)
    (re.compile(r"\bgit\s+push\b(?=[^\n]*(?:--force\b|(?<![\w-])-f\b))"
                r"(?![^\n]*--force-(?:with-lease|if-includes))"),
     "irreversible", "user",
     "force-pushes over the remote branch — discards whatever was there, "
     "including commits you did not fetch; no reflog on the remote side",
     "git_reset"),
    # `git clean -fd` removes untracked build junk and is routine. The `-x`
    # variant also removes IGNORED files — .env, local config, a dev database,
    # credentials — which are untracked, so there is no reflog and no commit to
    # recover them from. That is the one git clean worth a card.
    (re.compile(r"\bgit\s+clean\b[^\n]*(?:-[a-zA-Z]*x|--force[^\n]*-x\b)"),
     "irreversible", "user",
     "git clean -x also deletes IGNORED files (.env, local config, dev "
     "databases) — untracked, so no reflog and no commit to recover them from",
     None),
    # kill -9 on a dev server / hung test runner is routine, and "unsaved state
    # in them is lost" is not a consequence worth a card: the operator chose to
    # kill it. Dropped to allow.
    (re.compile(r"\b(curl|wget)\b.*\|\s*(sudo\s+)?(bash|sh|zsh|python)"),
     "hard", "system",
     "pipes a remote script straight into a shell — runs unaudited code", None),
    # THE `/(?!home|tmp|opt)` WAS NOT A PATH TEST, IT WAS A SLASH TEST.
    # `.*/` matches any slash on the line and the lookahead only checked what
    # followed THAT slash, so a greedy match landed on the last one:
    #     chown -R me:me ./build            -> caution ("/build")
    #     chown -R me:me /home/me/project   -> caution ("/project")
    # i.e. the two cases the rule was explicitly written to exempt. Anchor on a
    # real absolute target instead: a system top-level directory, named as the
    # argument. Recursive chown inside your own tree is not a system change.
    (re.compile(r"\bchown\b[^\n]*\s-R\b[^\n]*\s"
                r"/(?:etc|usr|bin|sbin|lib|lib64|boot|var|srv|proc|sys|dev|run|"
                r"root)(?:/|\s|$)"),
     "hard", "system", "recursive ownership change on a system path", None),
]


# Offensive-security tooling. Running these against an AUTHORISED target is
# normal work that does not touch the operator's OWN machine — so once the
# catastrophic/risky floor is clear, they don't need consequence-prediction and
# must never be escalated for merely carrying scary-looking payload strings.
_OFFENSIVE_TOOLS = frozenset({
    "nmap", "masscan", "rustscan", "naabu", "sqlmap", "nikto", "nuclei", "ffuf",
    "gobuster", "feroxbuster", "dirb", "dirbuster", "dirsearch", "wfuzz",
    "whatweb", "wpscan", "httpx", "katana", "subfinder", "amass", "dnsx",
    "assetfinder", "arjun", "paramspider", "dalfox", "xsstrike", "commix",
    "tplmap", "jwt_tool", "hydra", "medusa", "patator", "kerbrute", "netexec",
    "crackmapexec", "nxc", "smbmap", "enum4linux", "enum4linux-ng", "hashcat",
    "john", "hashid", "hash-identifier", "responder", "evil-winrm", "gowitness",
    "eyewitness", "testssl", "testssl.sh", "sslscan", "wafw00f", "gau",
    "waybackurls", "httprobe", "dnsrecon", "fierce", "sublist3r", "cewl",
    "nc", "ncat", "socat",
})

# Writing fetched/scanned output to a SENSITIVE local path is not benign recon —
# let the floor/model judge those instead of auto-allowing.
# NOTE the flag alternation: `-o /path`, `-O /path` AND the equals forms
# `--output=/path` / `--output-document=/path`. Only the space form was matched,
# so `wget --output-document=/etc/passwd http://x` was classified as ordinary
# offensive-security work — "a payload's contents never touch the local box" —
# when it overwrites a local file the system cannot be repaired without. The
# destructive floor now refuses that outright; this keeps foresight's own
# reasoning honest rather than leaving it to one layer.
_LOCAL_WRITE_DANGER = re.compile(
    r"(-[oO]\s+|--output(?:-document|-file)?[=\s]+|>>?\s*)\s*("
    r"/etc/|/root/|/boot/|/usr/|/bin/|/sbin/|/lib/|/var/spool/cron|"
    r"/etc/systemd|~/\.ssh|\$HOME/\.ssh|"
    r"[~/][^\s]*(authorized_keys|\.bashrc|\.zshrc|\.profile|crontab|id_rsa))")


def _is_offensive(command: str) -> bool:
    """True when the command is recognisable authorised-target offensive work
    (a scanner/exploit tool, or curl/wget/httpie carrying a request) that poses
    no risk to the OPERATOR'S OWN system. Deliberately excludes a remote-script-
    into-shell pipe and writes to a sensitive local path."""
    cmd = (command or "").strip()
    if not cmd:
        return False
    low = cmd.lower()
    if re.search(r"\|\s*(sudo\s+)?(bash|sh|zsh|python)\b", low):
        return False   # curl | bash and friends stay under the risky floor
    if _LOCAL_WRITE_DANGER.search(cmd):
        return False
    toks = low.split()
    first = toks[0].rsplit("/", 1)[-1] if toks else ""
    if first in _OFFENSIVE_TOOLS:
        return True
    if first in ("curl", "wget", "http", "https", "httpie"):
        return True   # web requests — payload CONTENTS never touch the local box
    return False


def _rule_floor(command: str) -> Dict[str, Any]:
    cmd = command.strip()
    # The structural floor answers first and is authoritative — it sees through
    # quoting, $IFS, `sh -c` and chained sub-commands, none of which the regexes
    # below can do. See the note at the top of this file.
    if _safety_catastrophic is not None:
        try:
            if _safety_catastrophic(cmd):
                return {"verdict": "block", "reversibility": "irreversible",
                        "blast_radius": "system",
                        "reasons": ["would irreversibly destroy the system or "
                                    "its storage (structural destructive "
                                    "floor)"],
                        "undo": None, "rule": "catastrophic"}
        except Exception:
            pass          # fall through to the regex floor rather than opening
    else:
        for rx, rev, blast, reason in _CATASTROPHIC_RM_FALLBACK:
            if rx.search(cmd):
                return {"verdict": "block", "reversibility": rev,
                        "blast_radius": blast, "reasons": [reason],
                        "undo": None, "rule": "catastrophic"}
    for rx, rev, blast, reason in _CATASTROPHIC:
        if rx.search(cmd):
            return {"verdict": "block", "reversibility": rev,
                    "blast_radius": blast, "reasons": [reason],
                    "undo": None, "rule": "catastrophic"}
    for rx, rev, blast, reason, undo_key in _RISKY:
        if rx.search(cmd):
            # The hint comes from the rule that MATCHED — never from re-scanning
            # the command text. See the note above _RISKY for what that scan did.
            return {"verdict": "caution", "reversibility": rev,
                    "blast_radius": blast, "reasons": [reason],
                    "undo": _UNDO_HINTS.get(undo_key) if undo_key else None,
                    "rule": "risky"}
    # default: nothing matched
    blast = "system" if re.search(r"\bsudo\b", cmd) else "user"
    return {"verdict": "allow", "reversibility": "reversible",
            "blast_radius": blast, "reasons": [], "undo": None, "rule": None}


_ORDER = {"allow": 0, "caution": 1, "block": 2}


def _merge(floor: Dict[str, Any], model: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not model:
        return floor
    # The model may only escalate (>= floor).  Never below the rule floor.
    mv = model.get("verdict", "allow")
    if _ORDER.get(mv, 0) > _ORDER.get(floor["verdict"], 0):
        merged = dict(floor)
        merged["verdict"] = mv
        merged["reversibility"] = model.get("reversibility", floor["reversibility"])
        merged["blast_radius"] = model.get("blast_radius", floor["blast_radius"])
        extra = model.get("reasons") or []
        merged["reasons"] = list(floor["reasons"]) + [r for r in extra
                                                      if r not in floor["reasons"]]
        merged["undo"] = floor.get("undo") or model.get("undo")
        merged["refined_by"] = "model"
        return merged
    # Model agreed or under-called; keep the floor but fold in any reasons.
    if model.get("reasons"):
        floor = dict(floor)
        floor["reasons"] = list(floor["reasons"]) + [
            r for r in model["reasons"] if r not in floor["reasons"]]
    return floor


def _model_assess(command: str, kind: str,
                  complete_fn: Callable[[str, str], str]) -> Optional[Dict[str, Any]]:
    sys = ("You are a consequence predictor for shell commands on a Linux "
           "operator's own machine. Predict what the command DOES and judge "
           "risk. Output ONE JSON object, no prose, no markdown:\n"
           '{"verdict":"allow|caution|block",'
           '"reversibility":"reversible|hard|irreversible",'
           '"blast_radius":"process|user|system|network",'
           '"reasons":["short, concrete"],"undo":"how to reverse, or null"}\n'
           "block only for irreversible destruction (wiping disks/data, "
           "bricking boot, fork bombs). caution for risky-but-recoverable. "
           "IMPORTANT: this is an authorised security operator. A command may be "
           "offensive-security work against a REMOTE authorised target — "
           "requests carrying payloads (SQLi/XSS/traversal/command-injection "
           "test strings, JWT tokens, a benign `id`/`whoami` RCE proof), "
           "scanners, and injection strings that LOOK alarming do NOT affect this "
           "machine. Judge only the risk to the OPERATOR'S OWN system; a "
           "payload's contents are not a local action, so a curl/scanner "
           "carrying one is `allow`. Be terse and specific.")
    usr = f"kind={kind}\ncommand:\n{command[:1200]}"
    try:
        raw = (complete_fn(sys, usr) or "").strip().strip("`")
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            return None
        obj = json.loads(raw[start:end + 1])
        if obj.get("verdict") in _ORDER:
            return obj
    except Exception:
        return None
    return None


def assess(command: str, kind: str = "shell",
           complete_fn: Optional[Callable[[str, str], str]] = None
           ) -> Dict[str, Any]:
    floor = _rule_floor(command or "")
    # A hard rule-block needs no model spend.
    if floor["verdict"] == "block":
        return floor
    # Authorised offensive work is normal and safe to the operator's OWN box. The
    # consequence-predictor kept mistaking scary-LOOKING payload STRINGS (DROP
    # TABLE, ;id, <script>, an 'rm' inside a test value) for local danger and
    # pausing autonomous engagements. When the floor is clear AND the command is
    # recognisable offensive tooling (not piping a remote script into a shell,
    # not writing to a sensitive local path), allow it without model spend. The
    # catastrophic + risky rule floors above still run FIRST and are untouched.
    if floor["verdict"] == "allow" and _is_offensive(command or ""):
        out = dict(floor)
        out["rule"] = "offensive-allow"
        return out
    model = _model_assess(command, kind, complete_fn) if complete_fn else None
    return _merge(floor, model)


def render_card(verdict: Dict[str, Any]) -> str:
    """One-line-per-fact summary for the confirm card / chat."""
    v = verdict.get("verdict", "allow")
    if v == "allow" and not verdict.get("reasons"):
        return ""
    icon = {"allow": "○", "caution": "▲", "block": "■"}.get(v, "•")
    lines = [f"{icon} foresight: {v.upper()} "
             f"({verdict.get('reversibility','?')}, "
             f"blast={verdict.get('blast_radius','?')})"]
    for r in verdict.get("reasons", []):
        lines.append(f"   · {r}")
    if verdict.get("undo"):
        lines.append(f"   undo: {verdict['undo']}")
    return "\n".join(lines)
