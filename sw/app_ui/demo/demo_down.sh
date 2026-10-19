#!/usr/bin/env bash
# Stop what demo_up.sh started: demo server, real_cell, fake cells, zones, the MNs and the IN. mosquitto stays up.
# Usage: bash demo_down.sh [quiet]
pkill -f "mosquitto_sub -t #"; pkill -f "server.py --live"; pkill -f "server.py --replay"; pkill -f "real_cell.py"; pkill -f "fake_cell.py"; pkill -f "polagrid.closed_loop"
bash ~/polargrid/nodes.sh stop >/dev/null
for p in $(pgrep -x server); do case "$(readlink /proc/$p/cwd)" in $HOME/polargrid/in_nolock) kill "$p";; esac; done
sleep 2
[ "$1" = quiet ] || echo "stopped (mosquitto left running)"
