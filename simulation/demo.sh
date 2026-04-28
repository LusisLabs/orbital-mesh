#!/usr/bin/env bash
# simulation/demo.sh — split-pane demo launcher.
#
# Sets up a tmux session with three panes, each watching one of the
# demo runner's output streams. After this attaches, run:
#
#     python -m simulation.demo
#
# in another terminal (or in the bottom pane after detaching with
# Ctrl-b d). The panes will populate live as faults are injected.
#
# Usage:
#     ./simulation/demo.sh            # 3-pane viewer only
#     ./simulation/demo.sh --auto     # adds a 4th pane that runs the demo
#     ./simulation/demo.sh --kill     # tear down the session

set -euo pipefail

DEMO_DIR=/tmp/mesh-demo
SESSION=mesh-demo

case "${1:-}" in
  --kill)
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    echo "killed tmux session $SESSION"
    exit 0
    ;;
esac

# Reset log files so the panes start clean. The demo runner does the
# same when it starts, but we want the panes to look ready before any
# command is typed.
mkdir -p "$DEMO_DIR"
: > "$DEMO_DIR/chaos.log"
: > "$DEMO_DIR/mesh.log"
cat > "$DEMO_DIR/node.txt" <<'EOF'

  NODE   (waiting for demo runner to start...)


  Run in another terminal:

      python -m simulation.demo

  Or pass --auto to this script to launch the runner in a 4th pane.

EOF

# Tear down any old session so re-running the script is idempotent.
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Build the layout. Geometry is approximate; tmux will reflow on attach.
#
#   ┌────────────────┬────────────────┐
#   │ NODE           │ CHAOS          │
#   ├────────────────┴────────────────┤
#   │ MESH                            │
#   └─────────────────────────────────┘
#
tmux new-session -d -s "$SESSION" -x 220 -y 60 \
  "watch -n 0.5 -t -c cat $DEMO_DIR/node.txt"

# Top-right: chaos log
tmux split-window -h -t "$SESSION:0.0" \
  "tail -F $DEMO_DIR/chaos.log"

# Bottom (full width spans both above): mesh log
tmux select-pane -t "$SESSION:0.0"
tmux split-window -v -t "$SESSION:0.0" -p 60 \
  "tail -F $DEMO_DIR/mesh.log"
# That last split happens on the left pane only; rejoin it across the
# full width by un-splitting and re-splitting at the window root.
tmux select-layout -t "$SESSION:0" main-horizontal
# main-horizontal: large pane on top, smaller below. Move our 'mesh'
# pane to be the small bottom one — the visual we want is two equal
# top panes (node + chaos) + a wide bottom pane (mesh).
tmux select-pane -t "$SESSION:0.0"

if [[ "${1:-}" == "--auto" ]]; then
  # tmux panes do not reliably inherit arbitrary newly-exported shell
  # variables, especially when a tmux server was already running. Copy
  # observer config explicitly into the session so ``--auto`` behaves
  # the same as running the command directly in the current shell.
  for name in \
    ANTHROPIC_API_KEY \
    MESH_OBSERVER_ENABLED \
    MESH_OBSERVER_PROVIDER \
    MESH_OBSERVER_BASE_URL \
    MESH_OBSERVER_MODEL \
    MESH_OBSERVER_API_KEY \
    MESH_OBSERVER_TIMEOUT_SECONDS \
    MESH_OBSERVER_MAX_TOKENS
  do
    if [[ -n "${!name:-}" ]]; then
      tmux set-environment -t "$SESSION" "$name" "${!name}"
    fi
  done

  # Add a small 4th pane on the very bottom that runs the demo.
  tmux split-window -v -t "$SESSION:0" -p 12 \
    "PYTHONPATH=. uvx --with-editable . --with deepagents python -m simulation.demo; echo '[demo] press any key to detach'; read -n1"
fi

# Status line tweak so panes show what's in them.
tmux set-option -t "$SESSION" pane-border-status top
tmux set-option -t "$SESSION" pane-border-format " #{pane_index}: #{pane_current_command} "

cat <<EOM
tmux session '$SESSION' is up.

If you used --auto, the demo is already running.
Otherwise, in another terminal run:

    export ANTHROPIC_API_KEY=sk-ant-...   # to engage the LLM observer
    python -m simulation.demo

To detach the tmux session: Ctrl-b d
To reattach later:           tmux attach -t $SESSION
To tear down:                ./simulation/demo.sh --kill

Attaching now...
EOM
sleep 1
tmux attach -t "$SESSION"
