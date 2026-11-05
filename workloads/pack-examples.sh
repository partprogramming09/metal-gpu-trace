#!/bin/sh
# Usage: pack-examples.sh <bgfx dir> <out dir>: one flat folder with both binaries and only the assets the examples load
set -eu
bgfx=$1
out=$2
runtime=$bgfx/examples/runtime
# temp: 40-svt writes its 370 MB tile cache there on the first run and crashes without the folder
mkdir -p "$out/shaders" "$out/textures" "$out/meshes" "$out/font" "$out/images" "$out/text" "$out/temp"
cp "$(find "$bgfx/.build/osx-arm64/bin" -type f -name examplesRelease)" "$out/examples"
cp "$(find "$bgfx/.build/win64_mingw-gcc/bin" -type f -name examplesRelease.exe)" "$out/examples.exe"
cp -R "$runtime/shaders/metal" "$runtime/shaders/dxbc" "$runtime/shaders/dxil" "$out/shaders/"
for asset in textures/fieldstone-n.dds textures/fieldstone-rgba.dds textures/uffizi.ktx \
             meshes/bunny.bin meshes/column.bin meshes/cube.bin meshes/hollowcube.bin meshes/orb.bin meshes/tree.bin \
             meshes/unit_sphere.bin textures/8k_mars.jpg textures/particle.ktx textures/figure-rgba.dds textures/flare.dds \
             textures/pf_alpha_test.dds textures/pf_uv_filtering_test.dds images/blender_icons16.png \
             meshes/bunny_decimated.bin textures/parallax-d.ktx textures/parallax-h.ktx textures/parallax-n.ktx \
             textures/dmap.png text/sherlock_holmes_a_scandal_in_bohemia_arthur_conan_doyle.txt; do
  cp "$runtime/$asset" "$out/$asset"
done
# 08-update and 47-pixelformats read every compressed-format sample; 10-font and 20-nanovg read the fonts;
# 20-nanovg builds image1.jpg to image12.jpg from a format string and stops loading at the first missing one
cp "$runtime"/textures/texture_compression_* "$out/textures/"
cp "$runtime"/images/image*.jpg "$out/images/"
cp "$runtime"/font/*.ttf "$runtime"/font/*.otf "$out/font/"
