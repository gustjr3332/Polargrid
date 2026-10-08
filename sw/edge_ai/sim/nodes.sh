#!/usr/bin/env bash
# 노드 실행/중지/상태: ./nodes.sh start|stop|status [N]
OUT=~/polargrid/nodes
case "$1" in
  start) n=0; for d in $(ls -d $OUT/mn* | head -n ${2:-1000}); do (cd $d && nohup ./server >server.log 2>&1 </dev/null &); n=$((n+1)); sleep 0.05; done; echo "started $n" ;;
  stop)  pkill -f "$OUT/mn" ; for p in $(pgrep -x server); do case "$(readlink /proc/$p/cwd)" in $OUT/*) kill $p;; esac; done; echo stopped ;;
  status) c=0; r=0; for p in $(pgrep -x server); do case "$(readlink /proc/$p/cwd)" in $OUT/*) c=$((c+1)); r=$((r+$(awk '/VmRSS/{print $2}' /proc/$p/status)));; esac; done; echo "running: $c  total RSS: $((r/1024)) MB" ;;
  *) echo "usage: $0 start|stop|status [N]" ;;
esac
