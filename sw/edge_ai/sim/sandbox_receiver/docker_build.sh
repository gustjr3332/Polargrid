#!/bin/sh
# Build only; pushing is a manual step (see README).
cd "$(dirname "$0")" && docker build --platform linux/amd64 -t polagrid-rx:latest .
