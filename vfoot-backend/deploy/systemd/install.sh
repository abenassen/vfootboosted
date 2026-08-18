#!/usr/bin/env bash
#
# Installa le unita' schedulate di Vfoot. Da eseguire COME ROOT SUL SERVER, dopo
# aver copiato la cartella (o dal checkout stesso: /srv/vfoot-app/vfoot-backend/deploy).
#
#   ./install.sh                      # copia le unita', daemon-reload, NON accende niente
#   ./install.sh --dry-run            # dice cosa farebbe
#   ./install.sh --enable tm-poll     # copia e accende un timer
#   ./install.sh --enable-all         # copia e accende tutto (go-live)
#   ./install.sh --status             # cosa e' acceso adesso e quando scatta
#
# Installare non accende: e' la scelta deliberata con cui il server sta oggi, con
# tutto pronto e spento. Accendere e' un gesto separato e nominato.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR=/etc/systemd/system
BACKUP_SRC="$HERE/../backup/vfoot-backup"
BACKUP_DST=/usr/local/sbin/vfoot-backup
MAINT_SRC="$HERE/../agent/vfoot-maintenance"
MAINT_DST=/usr/local/sbin/vfoot-maintenance
MAINT_SUDOERS_SRC="$HERE/../agent/vfoot-maintenance.sudoers"
MAINT_SUDOERS_DST=/etc/sudoers.d/vfoot-maintenance

# L'inventario. Aggiungere un job = una riga qui + i due file dell'unita'.
ALL_UNITS=(tick calendar tm-poll egress-refill market nudge digest backup health agent maintenance)

DRY=""
ENABLE=()
MODE=install

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)    DRY=1 ;;
    --enable)     shift; ENABLE+=("$1") ;;
    --enable-all) ENABLE=("${ALL_UNITS[@]}") ;;
    --status)     MODE=status ;;
    -h|--help)    sed -n '2,20p' "$0"; exit 0 ;;
    *)            echo "opzione sconosciuta: $1" >&2; exit 2 ;;
  esac
  shift
done

run() {
  if [ -n "$DRY" ]; then echo "[dry-run] $*"; else "$@"; fi
}

if [ "$MODE" = status ]; then
  systemctl list-timers --all 'vfoot-*' || true
  echo
  for u in "${ALL_UNITS[@]}"; do
    # is-enabled scrive "not-found" su stdout ED esce diverso da zero: senza
    # normalizzarlo si finisce per stampare due righe per unita'.
    state=$(systemctl is-enabled "vfoot-$u.timer" 2>/dev/null || true)
    if [ -z "$state" ] || [ "$state" = "not-found" ]; then
      state="non installato"
    fi
    printf '  %-20s %s\n' "vfoot-$u" "$state"
  done
  exit 0
fi

if [ -z "$DRY" ] && [ "$(id -u)" != 0 ]; then
  echo "Serve root: le unita' vanno in $UNIT_DIR." >&2
  exit 1
fi

echo "== Copio le unita' in $UNIT_DIR"
for u in "${ALL_UNITS[@]}"; do
  for kind in service timer; do
    src="$HERE/vfoot-$u.$kind"
    [ -f "$src" ] || { echo "  MANCA $src" >&2; exit 1; }
    run install -m 0644 "$src" "$UNIT_DIR/vfoot-$u.$kind"
  done
  echo "  vfoot-$u"
done

# Lo script di backup non e' un'unita' ma senza di lui vfoot-backup.service non
# parte: si installa qui, cosi' non si puo' dimenticare.
if [ -f "$BACKUP_SRC" ]; then
  echo "== Installo $BACKUP_DST"
  run install -m 0755 "$BACKUP_SRC" "$BACKUP_DST"
fi

# Il ponte sudo della manutenzione: senza di lui l'esecutore non puo' riavviare
# ne' ripristinare, cioe' non puo' fare niente di cio' per cui esiste. La regola
# sudoers si valida PRIMA di installarla: un file sudoers rotto in /etc/sudoers.d
# puo' togliere sudo a tutti, e questo e' l'unico posto in cui accorgersene costa
# ancora zero.
if [ -f "$MAINT_SRC" ]; then
  echo "== Installo $MAINT_DST + regola sudoers"
  run install -m 0755 "$MAINT_SRC" "$MAINT_DST"
  if [ -n "$DRY" ]; then
    echo "[dry-run] visudo -cf $MAINT_SUDOERS_SRC && install -m 0440 ... $MAINT_SUDOERS_DST"
  elif visudo -cf "$MAINT_SUDOERS_SRC" >/dev/null; then
    install -m 0440 "$MAINT_SUDOERS_SRC" "$MAINT_SUDOERS_DST"
  else
    echo "  REGOLA SUDOERS NON VALIDA: non installata (vedi $MAINT_SUDOERS_SRC)" >&2
  fi
fi

run systemctl daemon-reload

if [ ${#ENABLE[@]} -gt 0 ]; then
  echo "== Accendo: ${ENABLE[*]}"
  for u in "${ENABLE[@]}"; do
    case " ${ALL_UNITS[*]} " in
      *" $u "*) ;;
      *) echo "  unita' sconosciuta: $u (valide: ${ALL_UNITS[*]})" >&2; exit 2 ;;
    esac
    # calendar e tick escono verso SofaScore attraverso il ponte sudo: accenderli
    # senza di quello significa un fallimento al minuto nel journal.
    if [ "$u" = calendar ] || [ "$u" = tick ]; then
      if [ ! -x /usr/local/sbin/vfoot-egress ]; then
        echo "  SALTO vfoot-$u: manca /usr/local/sbin/vfoot-egress (vedi DEPLOY.md)" >&2
        continue
      fi
    fi
    # L'esecutore riavvia e ripristina: senza il suo ponte sudo non puo' fare
    # niente di cio' per cui esiste, e una proposta approvata resterebbe li'.
    if [ "$u" = maintenance ]; then
      if [ ! -x /usr/local/sbin/vfoot-maintenance ]; then
        echo "  SALTO vfoot-$u: manca /usr/local/sbin/vfoot-maintenance (vedi DEPLOY.md)" >&2
        continue
      fi
    fi
    # L'agente senza adattatore configurato fallirebbe a ogni scatto. La
    # sorveglianza deterministica (vfoot-health) non dipende da lui: se questo
    # resta spento, il sistema e' sorvegliato lo stesso, solo senza diagnosi.
    if [ "$u" = agent ]; then
      if ! grep -q '^VFOOT_AGENT_CMD=..*' /srv/vfoot-app/.env 2>/dev/null; then
        echo "  SALTO vfoot-$u: VFOOT_AGENT_CMD non e' impostata in .env" >&2
        continue
      fi
    fi
    run systemctl enable --now "vfoot-$u.timer"
  done
else
  echo "== Nessun timer acceso (usa --enable <nome> o --enable-all)"
fi

echo
echo "Stato attuale:"
[ -n "$DRY" ] || systemctl list-timers --all 'vfoot-*' || true
