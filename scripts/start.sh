#!/bin/sh
# Открывает три окна квеста в одной сессии tmux:
#   слева  — терминал игроков,
#   справа сверху — чат с разумом,
#   справа снизу  — пульт ведущего.
#
# Использование:  ./scripts/start.sh  [--офлайн]
set -e

КОРЕНЬ=$(cd "$(dirname "$0")/.." && pwd)
СЕССИЯ=энтропия

if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux не найден. Откройте три окна терминала вручную и запустите:"
    echo "  python3 run_terminal.py"
    echo "  python3 run_chat.py $*"
    echo "  python3 run_master.py"
    exit 1
fi

if tmux has-session -t "$СЕССИЯ" 2>/dev/null; then
    echo "Сессия «$СЕССИЯ» уже открыта — подключаюсь."
    exec tmux attach -t "$СЕССИЯ"
fi

tmux new-session  -d -s "$СЕССИЯ" -c "$КОРЕНЬ" "python3 run_terminal.py"
tmux split-window -h -t "$СЕССИЯ" -c "$КОРЕНЬ" "python3 run_chat.py $*"
tmux split-window -v -t "$СЕССИЯ" -c "$КОРЕНЬ" "python3 run_master.py"
tmux select-pane  -t "$СЕССИЯ".0
exec tmux attach -t "$СЕССИЯ"
