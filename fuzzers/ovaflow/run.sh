#!/bin/bash
set -e

export AFL_SKIP_CPUFREQ=1
export AFL_NO_AFFINITY=1

cd "$OUT"
"$FUZZER/repo/zg-new" -m none -t 2000+ \
    -i "$TARGET/corpus" -o "$SHARED" \
    $FUZZER_ARGS -- $TAEGET_ARGS
