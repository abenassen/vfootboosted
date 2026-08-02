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

# L'inventario. Aggiungere un job = una riga qui + i due file dell'unita'.
ALL_UNITS=(tick calendar tm-poll egress-refill market nudge backup)

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
    run systemctl enable --now "vfoot-$u.timer"
  done
else
  echo "== Nessun timer acceso (usa --enable <nome> o --enable-all)"
fi

echo
echo "Stato attuale:"
[ -n "$DRY" ] || systemctl list-timers --all 'vfoot-*' || true
