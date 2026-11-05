#!/bin/sh
# Usage: pack-examples.sh <bgfx dir> <out dir>: one flat folder with both binaries and only the assets the examples load
set -eu
bgfx=$1
out=$2
runtime=$bgfx/examples/runtime
mkdir -p "$out/shaders" "$out/textures" "$out/meshes"
cp "$(find "$bgfx/.build/osx-arm64/bin" -type f -name examplesRelease)" "$out/examples"
cp "$(find "$bgfx/.build/win64_mingw-gcc/bin" -type f -name examplesRelease.exe)" "$out/examples.exe"
cp -R "$runtime/shaders/metal" "$runtime/shaders/dxbc" "$out/shaders/"
for asset in textures/fieldstone-n.dds textures/fieldstone-rgba.dds textures/uffizi.ktx \
             meshes/bunny.bin meshes/column.bin meshes/cube.bin meshes/hollowcube.bin meshes/orb.bin meshes/tree.bin \
             meshes/unit_sphere.bin; do
  cp "$runtime/$asset" "$out/$asset"
done
