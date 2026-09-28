#!/usr/bin/env bash
# Build Kaldi and its dependencies (OpenBLAS, OpenFst) as static libraries into
# $KALDI_ROOT, for linking into kalpy's standalone wheels (KALPY_STATIC_KALDI).
#
# This mirrors the conda-forge kaldi recipe (same Kaldi commit and patch, same
# OpenFst version and CMake configuration) so that wheels and conda packages
# behave the same, but uses the toolchain of the build environment: inside the
# manylinux containers this gives wheels with a portable manylinux tag.
#
# Usage: KALDI_ROOT=/path/to/prefix scripts/build_kaldi.sh
set -euxo pipefail

: "${KALDI_ROOT:?KALDI_ROOT must be set to the installation prefix}"

OPENBLAS_VERSION=0.3.34
OPENBLAS_SHA256=cd7e129868320cc2d033afa920e31202dfe0b8066a5b66661900ccc0f197dfed
OPENFST_VERSION=1.8.4
OPENFST_SHA256=a8ebbb6f3d92d07e671500587472518cfc87cb79b9a654a5a8abb2d0eb298016
# Keep in sync with https://github.com/conda-forge/kaldi-feedstock
KALDI_VERSION=5.5.1172
KALDI_COMMIT=f4007661023b98b8081fd875029f0dee62242fd1
KALDI_SHA256=139de58f1abbf727fee65e709a8fcc6d8714d5e5596a7eb15491faef1ac73304

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${KALDI_BUILD_DIR:-$(mktemp -d)}"
NPROC="$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu)"
ARCH="$(uname -m)"

if [[ -f "$KALDI_ROOT/lib/cmake/kalpy-deps.done" ]]; then
    echo "Kaldi already built in $KALDI_ROOT"
    exit 0
fi

fetch() {
    local url="$1" sha="$2" out="$3"
    curl -fsSL --retry 5 -o "$out" "$url"
    if command -v sha256sum >/dev/null; then
        echo "$sha  $out" | sha256sum -c -
    else
        echo "$sha  $out" | shasum -a 256 -c -
    fi
}

mkdir -p "$KALDI_ROOT" "$SRC_DIR"
cd "$SRC_DIR"

# Position independent (linked into a Python extension), one section per
# function so the final link can drop what the bindings never use, and no
# debug information.
export CFLAGS="-O2 -g0 -fPIC -ffunction-sections -fdata-sections"
export CXXFLAGS="$CFLAGS"
if [[ "$(uname)" == "Darwin" ]]; then
    # Same as conda-forge: ignore libc++ availability annotations of the old SDK
    export CXXFLAGS="$CXXFLAGS -D_LIBCPP_DISABLE_AVAILABILITY"
fi

# --- OpenBLAS (with LAPACK and LAPACKE, no Fortran compiler needed) ---
# DYNAMIC_ARCH selects kernels at runtime; TARGET sets the baseline for the
# common code so the library runs on any CPU of the architecture. Kernels are
# limited to a few CPU families; others use the closest one in the list.
if [[ "$ARCH" == "x86_64" ]]; then
    OPENBLAS_TARGET=PRESCOTT
    OPENBLAS_DYNAMIC_LIST="PRESCOTT NEHALEM SANDYBRIDGE HASWELL SKYLAKEX ZEN"
else
    OPENBLAS_TARGET=ARMV8
    OPENBLAS_DYNAMIC_LIST="ARMV8 NEOVERSEN1 NEOVERSEV1 NEOVERSEN2 VORTEX"
fi
OPENBLAS_OPTIONS=(DYNAMIC_ARCH=1 TARGET="$OPENBLAS_TARGET"
    DYNAMIC_LIST="$OPENBLAS_DYNAMIC_LIST" NOFORTRAN=1 C_LAPACK=1
    USE_OPENMP=0 NUM_THREADS=64 COMMON_OPT="$CFLAGS")
# The shared library is only there for Kaldi's CMake BLAS detection; kalpy
# links libopenblas.a.
fetch "https://github.com/OpenMathLib/OpenBLAS/releases/download/v${OPENBLAS_VERSION}/OpenBLAS-${OPENBLAS_VERSION}.tar.gz" \
    "$OPENBLAS_SHA256" openblas.tar.gz
tar xzf openblas.tar.gz
make -C "OpenBLAS-${OPENBLAS_VERSION}" -j"$NPROC" "${OPENBLAS_OPTIONS[@]}" libs shared
make -C "OpenBLAS-${OPENBLAS_VERSION}" "${OPENBLAS_OPTIONS[@]}" PREFIX="$KALDI_ROOT" install

# --- OpenFst ---
fetch "https://www.openfst.org/twiki/pub/FST/FstDownload/openfst-${OPENFST_VERSION}.tar.gz" \
    "$OPENFST_SHA256" openfst.tar.gz
tar xzf openfst.tar.gz
(
    cd "openfst-${OPENFST_VERSION}"
    ./configure --prefix="$KALDI_ROOT" --enable-static --disable-shared --with-pic \
        --enable-compress --enable-fsts --enable-grm --enable-special
    make -j"$NPROC"
    make install
)

# --- Kaldi ---
fetch "https://github.com/kaldi-asr/kaldi/archive/${KALDI_COMMIT}.tar.gz" \
    "$KALDI_SHA256" kaldi.tar.gz
tar xzf kaldi.tar.gz
cd "kaldi-${KALDI_COMMIT}"
patch -p1 < "$SCRIPT_DIR/patches/kaldi-0001-Shared-libraries-on-windows.patch"
# Kaldi's "conda" mode uses the OpenFst and BLAS found in CONDA_ROOT and reads
# LAPACKE headers from $PREFIX/include.
export PREFIX="$KALDI_ROOT"
cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$KALDI_ROOT" \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DCMAKE_PREFIX_PATH="$KALDI_ROOT" \
    -DCONDA_ROOT="$KALDI_ROOT" \
    -DBLA_VENDOR=OpenBLAS \
    -DBUILD_SHARED_LIBS=OFF \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DKALDI_BUILD_EXE=OFF \
    -DKALDI_BUILD_TEST=OFF \
    -DKALDI_VERSION="$KALDI_VERSION" \
    -DPython3_EXECUTABLE="$(command -v python3)"
cmake --build build -j"$NPROC"
cmake --install build --component kaldi

mkdir -p "$KALDI_ROOT/lib/cmake"
touch "$KALDI_ROOT/lib/cmake/kalpy-deps.done"
