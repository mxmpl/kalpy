# Superbuild of Kaldi and its dependencies (OpenBLAS, OpenFst) as static
# libraries, for linking into kalpy's standalone wheels (KALPY_STATIC_KALDI).
#
# This mirrors the conda-forge kaldi recipe (same Kaldi commit and patch, same
# OpenFst version and CMake configuration) so that wheels and conda packages
# behave the same, but uses the toolchain of the build environment: inside the
# manylinux containers this gives wheels with a portable manylinux tag.
#
# Usage:
#   cmake -S deps -B build/deps -DCMAKE_INSTALL_PREFIX=/path/to/prefix
#   cmake --build build/deps
# then build kalpy with KALDI_ROOT=/path/to/prefix.
#
# Every step of every dependency (download, patch, configure, build, install)
# has its own stamp file, so a failed build resumes where it stopped. Source
# archives are kept in KALPY_DEPS_DOWNLOAD_DIR, which can be cached in CI.
cmake_minimum_required(VERSION 3.24)
project(kalpy-deps LANGUAGES NONE)

include(ExternalProject)

if(CMAKE_INSTALL_PREFIX_INITIALIZED_TO_DEFAULT)
    message(FATAL_ERROR "Set CMAKE_INSTALL_PREFIX to the prefix kalpy will use as KALDI_ROOT")
endif()
set(PREFIX "${CMAKE_INSTALL_PREFIX}")

set(KALPY_DEPS_DOWNLOAD_DIR "${CMAKE_BINARY_DIR}/downloads" CACHE PATH
    "Where source archives are downloaded (cacheable)")

set(OPENBLAS_VERSION 0.3.34)
set(OPENBLAS_SHA256 cd7e129868320cc2d033afa920e31202dfe0b8066a5b66661900ccc0f197dfed)
set(OPENFST_VERSION 1.8.4)
set(OPENFST_SHA256 a8ebbb6f3d92d07e671500587472518cfc87cb79b9a654a5a8abb2d0eb298016)
# Keep in sync with https://github.com/conda-forge/kaldi-feedstock
set(KALDI_VERSION 5.5.1172)
set(KALDI_COMMIT f4007661023b98b8081fd875029f0dee62242fd1)
set(KALDI_SHA256 139de58f1abbf727fee65e709a8fcc6d8714d5e5596a7eb15491faef1ac73304)

# URLs are tried in order: openfst.org refuses downloads from some CI runners,
# so a mirror can be put first (the archive is checked against the hash anyway).
set(KALPY_OPENFST_URLS
    "https://www.openfst.org/twiki/pub/FST/FstDownload/openfst-${OPENFST_VERSION}.tar.gz"
    CACHE STRING "Semicolon-separated list of URLs for the OpenFst archive")

find_program(MAKE_EXECUTABLE NAMES gmake make REQUIRED)
find_program(PATCH_EXECUTABLE patch REQUIRED)
find_program(PYTHON3_EXECUTABLE python3 REQUIRED)
cmake_host_system_information(RESULT NPROC QUERY NUMBER_OF_LOGICAL_CORES)

# Position independent (linked into a Python extension), one section per
# function so the final link can drop what the bindings never use, and no
# debug information.
set(DEPS_CFLAGS "-O2 -g0 -fPIC -ffunction-sections -fdata-sections")
set(DEPS_CXXFLAGS "${DEPS_CFLAGS}")
if(APPLE)
    # Same as conda-forge: ignore libc++ availability annotations of the old SDK
    string(APPEND DEPS_CXXFLAGS " -D_LIBCPP_DISABLE_AVAILABILITY")
endif()
set(DEPS_ENV ${CMAKE_COMMAND} -E env "CFLAGS=${DEPS_CFLAGS}" "CXXFLAGS=${DEPS_CXXFLAGS}")

# --- OpenBLAS (with LAPACK and LAPACKE, no Fortran compiler needed) ---
# DYNAMIC_ARCH selects kernels at runtime; TARGET sets the baseline for the
# common code so the library runs on any CPU of the architecture. Kernels are
# limited to a few CPU families; others use the closest one in the list.
if(CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "^(x86_64|AMD64|amd64)$")
    set(OPENBLAS_TARGET PRESCOTT)
    set(OPENBLAS_DYNAMIC_LIST "PRESCOTT NEHALEM SANDYBRIDGE HASWELL SKYLAKEX ZEN")
else()
    set(OPENBLAS_TARGET ARMV8)
    set(OPENBLAS_DYNAMIC_LIST "ARMV8 NEOVERSEN1 NEOVERSEV1 NEOVERSEN2 VORTEX")
endif()
set(OPENBLAS_OPTIONS DYNAMIC_ARCH=1 TARGET=${OPENBLAS_TARGET}
    "DYNAMIC_LIST=${OPENBLAS_DYNAMIC_LIST}" NOFORTRAN=1 C_LAPACK=1
    USE_OPENMP=0 NUM_THREADS=64 "COMMON_OPT=${DEPS_CFLAGS}")

# The shared library is only there for Kaldi's CMake BLAS detection; kalpy
# links libopenblas.a.
ExternalProject_Add(openblas
    URL "https://github.com/OpenMathLib/OpenBLAS/releases/download/v${OPENBLAS_VERSION}/OpenBLAS-${OPENBLAS_VERSION}.tar.gz"
    URL_HASH SHA256=${OPENBLAS_SHA256}
    DOWNLOAD_DIR "${KALPY_DEPS_DOWNLOAD_DIR}"
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    BUILD_IN_SOURCE TRUE
    CONFIGURE_COMMAND ""
    BUILD_COMMAND ${DEPS_ENV} ${MAKE_EXECUTABLE} -j${NPROC} ${OPENBLAS_OPTIONS} libs shared
    INSTALL_COMMAND ${DEPS_ENV} ${MAKE_EXECUTABLE} ${OPENBLAS_OPTIONS} PREFIX=${PREFIX} install
    # Kaldi calls LAPACK routines without the hidden Fortran string-length
    # arguments that lapack.h declares since LAPACK 3.9.1. conda-forge compiles
    # Kaldi against the reference LAPACK 3.9.0 headers, which predate them; do
    # the same.
    COMMAND ${CMAKE_COMMAND} -DFILE=${PREFIX}/include/lapack.h
            -P ${CMAKE_CURRENT_SOURCE_DIR}/drop-lapack-strlen.cmake
    LOG_BUILD TRUE
    LOG_OUTPUT_ON_FAILURE TRUE
)

# --- OpenFst ---
ExternalProject_Add(openfst
    URL ${KALPY_OPENFST_URLS}
    URL_HASH SHA256=${OPENFST_SHA256}
    DOWNLOAD_DIR "${KALPY_DEPS_DOWNLOAD_DIR}"
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    BUILD_IN_SOURCE TRUE
    CONFIGURE_COMMAND ${DEPS_ENV} <SOURCE_DIR>/configure --prefix=${PREFIX}
        --enable-static --disable-shared --with-pic
        --enable-compress --enable-fsts --enable-grm --enable-special
    BUILD_COMMAND ${MAKE_EXECUTABLE} -j${NPROC}
    INSTALL_COMMAND ${MAKE_EXECUTABLE} install
    LOG_CONFIGURE TRUE
    LOG_BUILD TRUE
    LOG_OUTPUT_ON_FAILURE TRUE
)

# --- Kaldi ---
# Kaldi's "conda" mode uses the OpenFst and BLAS found in CONDA_ROOT and reads
# LAPACKE headers from $PREFIX/include.
ExternalProject_Add(kaldi
    DEPENDS openblas openfst
    URL "https://github.com/kaldi-asr/kaldi/archive/${KALDI_COMMIT}.tar.gz"
    URL_HASH SHA256=${KALDI_SHA256}
    DOWNLOAD_DIR "${KALPY_DEPS_DOWNLOAD_DIR}"
    DOWNLOAD_NAME "kaldi-${KALDI_COMMIT}.tar.gz"
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    PATCH_COMMAND ${PATCH_EXECUTABLE} -p1 -i
        ${CMAKE_CURRENT_SOURCE_DIR}/patches/kaldi-0001-Shared-libraries-on-windows.patch
    CONFIGURE_COMMAND ${DEPS_ENV} "PREFIX=${PREFIX}"
        ${CMAKE_COMMAND} -S <SOURCE_DIR> -B <BINARY_DIR>
        -DCMAKE_BUILD_TYPE=Release
        -DCMAKE_INSTALL_PREFIX=${PREFIX}
        -DCMAKE_INSTALL_LIBDIR=lib
        -DCMAKE_PREFIX_PATH=${PREFIX}
        -DCONDA_ROOT=${PREFIX}
        -DBLA_VENDOR=OpenBLAS
        -DBUILD_SHARED_LIBS=OFF
        -DCMAKE_POSITION_INDEPENDENT_CODE=ON
        -DKALDI_BUILD_EXE=OFF
        -DKALDI_BUILD_TEST=OFF
        -DKALDI_VERSION=${KALDI_VERSION}
        -DPython3_EXECUTABLE=${PYTHON3_EXECUTABLE}
    BUILD_COMMAND ${CMAKE_COMMAND} --build <BINARY_DIR> -j${NPROC}
    INSTALL_COMMAND ${CMAKE_COMMAND} --install <BINARY_DIR> --component kaldi
    LOG_CONFIGURE TRUE
    LOG_BUILD TRUE
    LOG_OUTPUT_ON_FAILURE TRUE
)
