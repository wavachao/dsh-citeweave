#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."
revision=ea6b9977f5a153215b38cd9a6aa3e4702ffbda22
if ! test -d reference/M2RAG/.git; then
    mkdir -p reference
    git clone https://github.com/maziao/M2RAG.git reference/M2RAG
fi
test "$(git -C reference/M2RAG rev-parse HEAD)" = "$revision" || git -C reference/M2RAG checkout --detach "$revision"
