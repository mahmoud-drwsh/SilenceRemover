#!/bin/sh
# Make the synthetic media that the integration flows read from /fixtures.
# The fresh-database mode runs this script in the app image, which has ffmpeg.
# The flows expect these exact files:
#   original.mp4    - short H.264/AAC video (originals and canonical card flows)
#   original.mkv    - the same video in Matroska (originals flow)
#   fractional.mp4  - 25.125 s video (source-processing flow). The flow checks
#                     this duration, so do not change the -t value.
set -eu
out="${1:-/fixtures}"
mkdir -p "$out"
make() {
  ffmpeg -nostdin -hide_banner -loglevel error -y \
    -f lavfi -i testsrc2=size=320x180:rate=24 -f lavfi -i sine=frequency=440 \
    -t "$1" -c:v libx264 -pix_fmt yuv420p -c:a aac "$2"
}
make 2 "$out/original.mp4"
make 2 "$out/original.mkv"
make 25.121 "$out/fractional.mp4"
ls -l "$out"
