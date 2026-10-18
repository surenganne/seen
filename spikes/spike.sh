#!/bin/bash
# usage: spike.sh NAME "prompt" [extra claude args...]  (env SPIKE_* passed through)
SP=${SEEN_SPIKE_DIR:?set SEEN_SPIKE_DIR}
N=$1; P=$2; shift 2
R=$SP/repos/$N; O=$SP/rec/$N; rm -rf $R $O; mkdir -p $SP/repos $O; cp -R $SP/spike-repo $R
cd $R && SPIKE_OUT=$O claude -p "$P" --plugin-dir $(cd $(dirname $0)/.. && pwd)/spikes/recorder --setting-sources project --model sonnet --max-budget-usd 1 --output-format stream-json --verbose "${@:---permission-mode=acceptEdits}" > $O/stream.jsonl 2> $O/stderr.txt
echo "rc=$?" > $O/rc
