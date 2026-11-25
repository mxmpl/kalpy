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
# On Windows, run this from a Visual Studio developer prompt (x64) with
# `-G Ninja`: everything is built with MSVC, except OpenBLAS which needs
# clang-cl for its optimized kernels. OpenFst is built with the CMake files of
# the conda-forge recipe instead of autotools, and dlfcn-win32 is added because
# OpenFst's headers include <dlfcn.h>. GNU patch is taken from Git for Windows.
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
# Keep in sync with https://github.com/conda-forge/kaldi-feedstock
set(KALDI_VERSION 5.5.1172)
set(KALDI_COMMIT f4007661023b98b8081fd875029f0dee62242fd1)
set(KALDI_SHA256 139de58f1abbf727fee65e709a8fcc6d8714d5e5596a7eb15491faef1ac73304)

# openfst.org is behind a Cloudflare challenge that refuses downloads from CI
# runners, so OpenFst comes from Debian's copy of the release.
# To use the official tarball instead, set
#   KALPY_OPENFST_URLS=https://www.openfst.org/twiki/pub/FST/FstDownload/openfst-1.8.4.tar.gz
#   KALPY_OPENFST_SHA256=a8ebbb6f3d92d07e671500587472518cfc87cb79b9a654a5a8abb2d0eb298016
set(KALPY_OPENFST_URLS
    "https://deb.debian.org/debian/pool/main/o/openfst/openfst_${OPENFST_VERSION}.orig.tar.bz2"
    "https://snapshot.debian.org/archive/debian/20250119T144132Z/pool/main/o/openfst/openfst_${OPENFST_VERSION}.orig.tar.bz2"
    CACHE STRING "Semicolon-separated list of URLs for the OpenFst archive")
set(KALPY_OPENFST_SHA256 48a7bf9eb85637f1e1d9f7519c418ed7c689cdedda652b51ffb9ab19df521041
    CACHE STRING "SHA-256 of the OpenFst archive")

cmake_host_system_information(RESULT NPROC QUERY NUMBER_OF_LOGICAL_CORES)

if(WIN32)
    if(NOT CMAKE_GENERATOR MATCHES "^Ninja")
        message(FATAL_ERROR "On Windows, configure with -G Ninja from a Visual Studio developer prompt")
    endif()
    find_program(PATCH_EXECUTABLE patch REQUIRED
                 HINTS "$ENV{ProgramFiles}/Git/usr/bin")
    find_program(CLANG_CL_EXECUTABLE clang-cl REQUIRED
                 HINTS "$ENV{ProgramFiles}/LLVM/bin")
    # python3.exe may be the Microsoft Store stub
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
    set(PYTHON3_EXECUTABLE "${Python3_EXECUTABLE}")

    # One COMDAT per function and per variable so the final link can drop what
    # the bindings never use (/OPT:REF), and the dynamic C runtime (/MD) like
    # Python and every extension module. The definitions are those Kaldi's
    # CMake only adds when building DLLs.
    # LAPACK_COMPLEX_CPP: with MSVC, OpenBLAS's lapacke_config.h ignores the
    # LAPACK_COMPLEX_STRUCTURE Kaldi defines and falls back to the C types
    # _Fcomplex/_Dcomplex, which do not exist in C++. Kaldi only calls real
    # LAPACK routines, so std::complex is fine.
    set(DEPS_CFLAGS "/Gy /Gw")
    set(DEPS_CXXFLAGS "${DEPS_CFLAGS} /bigobj /DWIN32_LEAN_AND_MEAN /DNOMINMAX /D_USE_MATH_DEFINES /D_SILENCE_ALL_CXX17_DEPRECATION_WARNINGS /DLAPACK_COMPLEX_CPP")
    set(DEPS_CMAKE_ARGS -G ${CMAKE_GENERATOR}
        -DCMAKE_BUILD_TYPE=Release
        -DCMAKE_INSTALL_PREFIX=${PREFIX}
        -DCMAKE_PREFIX_PATH=${PREFIX}
        -DCMAKE_POLICY_DEFAULT_CMP0091=NEW
        -DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreadedDLL)
else()
    find_program(MAKE_EXECUTABLE NAMES gmake make REQUIRED)
    find_program(AUTORECONF_EXECUTABLE autoreconf REQUIRED)
    find_program(LIBTOOLIZE_EXECUTABLE NAMES libtoolize glibtoolize REQUIRED)
    find_program(PATCH_EXECUTABLE patch REQUIRED)
    find_program(PYTHON3_EXECUTABLE python3 REQUIRED)

    # Position independent (linked into a Python extension), one section per
    # function so the final link can drop what the bindings never use, and no
    # debug information.
    set(DEPS_CFLAGS "-O2 -g0 -fPIC -ffunction-sections -fdata-sections")
    set(DEPS_CXXFLAGS "${DEPS_CFLAGS}")
    if(APPLE)
        # Same as conda-forge: ignore libc++ availability annotations of the old SDK
        string(APPEND DEPS_CXXFLAGS " -D_LIBCPP_DISABLE_AVAILABILITY")
    endif()
    set(DEPS_CMAKE_ARGS -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=${PREFIX}
        -DCMAKE_PREFIX_PATH=${PREFIX})
endif()
set(DEPS_ENV ${CMAKE_COMMAND} -E env "CFLAGS=${DEPS_CFLAGS}" "CXXFLAGS=${DEPS_CXXFLAGS}")
set(PATCHES_DIR "${CMAKE_CURRENT_SOURCE_DIR}/patches")
set(DROP_LAPACK_STRLEN ${CMAKE_COMMAND} -DFILE=${PREFIX}/include/lapack.h
    -P ${CMAKE_CURRENT_SOURCE_DIR}/drop-lapack-strlen.cmake)

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

if(WIN32)
# OpenBLAS's Makefiles need a Unix shell: use its CMake build. MSVC cannot
# compile the assembly kernels (it only builds the generic C ones, without
# DYNAMIC_ARCH), clang-cl can and produces MSVC-compatible objects. Only the
# static library is built (openblas.lib); the CMake build always adds the
# baseline target to DYNAMIC_LIST. Headers are installed in include/openblas and copied to
# include/, where Kaldi looks for them.
string(REPLACE "${OPENBLAS_TARGET} " "" OPENBLAS_CMAKE_DYNAMIC_LIST "${OPENBLAS_DYNAMIC_LIST}")
string(REPLACE " " "|" OPENBLAS_CMAKE_DYNAMIC_LIST "${OPENBLAS_CMAKE_DYNAMIC_LIST}")
ExternalProject_Add(openblas
    URL "https://github.com/OpenMathLib/OpenBLAS/releases/download/v${OPENBLAS_VERSION}/OpenBLAS-${OPENBLAS_VERSION}.tar.gz"
    URL_HASH SHA256=${OPENBLAS_SHA256}
    DOWNLOAD_DIR "${KALPY_DEPS_DOWNLOAD_DIR}"
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    LIST_SEPARATOR |
    CONFIGURE_COMMAND ${DEPS_ENV} ${CMAKE_COMMAND} -S <SOURCE_DIR> -B <BINARY_DIR>
        ${DEPS_CMAKE_ARGS}
        -DCMAKE_C_COMPILER=${CLANG_CL_EXECUTABLE}
        -DBUILD_STATIC_LIBS=ON
        -DBUILD_SHARED_LIBS=OFF
        -DBUILD_TESTING=OFF
        -DNOFORTRAN=ON
        -DC_LAPACK=ON
        -DUSE_OPENMP=OFF
        -DNUM_THREADS=64
        -DDYNAMIC_ARCH=ON
        -DTARGET=${OPENBLAS_TARGET}
        -DDYNAMIC_LIST=${OPENBLAS_CMAKE_DYNAMIC_LIST}
    BUILD_COMMAND ${CMAKE_COMMAND} --build <BINARY_DIR> -j${NPROC}
    INSTALL_COMMAND ${CMAKE_COMMAND} --install <BINARY_DIR>
    COMMAND ${CMAKE_COMMAND} -E copy_directory ${PREFIX}/include/openblas ${PREFIX}/include
    COMMAND ${DROP_LAPACK_STRLEN}
    LOG_CONFIGURE TRUE
    LOG_BUILD TRUE
    LOG_OUTPUT_ON_FAILURE TRUE
)
else()
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
    COMMAND ${DROP_LAPACK_STRLEN}
    LOG_BUILD TRUE
    LOG_OUTPUT_ON_FAILURE TRUE
)
endif()

# --- OpenFst ---
if(WIN32)
# dlfcn-win32: dlopen() for Windows, used by OpenFst to load FST extensions.
ExternalProject_Add(dlfcn-win32
    URL "https://github.com/dlfcn-win32/dlfcn-win32/archive/refs/tags/v1.4.2.tar.gz"
    URL_HASH SHA256=f61a874bc9163ab488accb364fd681d109870c86e8071f4710cbcdcbaf9f2565
    DOWNLOAD_DIR "${KALPY_DEPS_DOWNLOAD_DIR}"
    DOWNLOAD_NAME "dlfcn-win32-1.4.2.tar.gz"
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    CONFIGURE_COMMAND ${DEPS_ENV} ${CMAKE_COMMAND} -S <SOURCE_DIR> -B <BINARY_DIR>
        ${DEPS_CMAKE_ARGS}
        -DBUILD_SHARED_LIBS=OFF
        -DBUILD_TESTS=OFF
    BUILD_COMMAND ${CMAKE_COMMAND} --build <BINARY_DIR> -j${NPROC}
    INSTALL_COMMAND ${CMAKE_COMMAND} --install <BINARY_DIR>
    LOG_CONFIGURE TRUE
    LOG_BUILD TRUE
    LOG_OUTPUT_ON_FAILURE TRUE
)

# CMake build from the conda-forge recipe (openfst-0001), as static libraries
# (openfst-0002). Only libfst and libfstscript are needed.
ExternalProject_Add(openfst
    DEPENDS dlfcn-win32
    URL ${KALPY_OPENFST_URLS}
    URL_HASH SHA256=${KALPY_OPENFST_SHA256}
    DOWNLOAD_DIR "${KALPY_DEPS_DOWNLOAD_DIR}"
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    PATCH_COMMAND ${PATCH_EXECUTABLE} -p1 -i ${PATCHES_DIR}/openfst-0001-Add-CMake-files-and-Windows-compat.patch
    COMMAND ${PATCH_EXECUTABLE} -p1 -i ${PATCHES_DIR}/openfst-0002-Static-libraries-on-windows.patch
    CONFIGURE_COMMAND ${DEPS_ENV} ${CMAKE_COMMAND} -S <SOURCE_DIR> -B <BINARY_DIR>
        ${DEPS_CMAKE_ARGS}
        -DBUILD_SHARED_LIBS=OFF
        -DOPENFST_BUILD_TEST=OFF
        -DHAVE_BIN=OFF
        -DHAVE_COMPACT=OFF
        -DHAVE_COMPRESS=OFF
        -DHAVE_CONST=OFF
        -DHAVE_FAR=OFF
        -DHAVE_GRM=OFF
        -DHAVE_PDT=OFF
        -DHAVE_MPDT=OFF
        -DHAVE_LINEAR=OFF
        -DHAVE_LOOKAHEAD=OFF
        -DHAVE_NGRAM=OFF
        -DHAVE_PYTHON=OFF
        -DHAVE_SPECIAL=OFF
    BUILD_COMMAND ${CMAKE_COMMAND} --build <BINARY_DIR> -j${NPROC}
    INSTALL_COMMAND ${CMAKE_COMMAND} --install <BINARY_DIR>
    LOG_CONFIGURE TRUE
    LOG_BUILD TRUE
    LOG_OUTPUT_ON_FAILURE TRUE
)
else()
ExternalProject_Add(openfst
    URL ${KALPY_OPENFST_URLS}
    URL_HASH SHA256=${KALPY_OPENFST_SHA256}
    DOWNLOAD_DIR "${KALPY_DEPS_DOWNLOAD_DIR}"
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    BUILD_IN_SOURCE TRUE
    CONFIGURE_COMMAND ${CMAKE_COMMAND} -E env LIBTOOLIZE=${LIBTOOLIZE_EXECUTABLE}
        ${AUTORECONF_EXECUTABLE} --force --install
    COMMAND ${DEPS_ENV} <SOURCE_DIR>/configure --prefix=${PREFIX}
        --enable-static --disable-shared --with-pic
        --enable-compress --enable-fsts --enable-grm --enable-special
    BUILD_COMMAND ${MAKE_EXECUTABLE} -j${NPROC}
    INSTALL_COMMAND ${MAKE_EXECUTABLE} install
    LOG_CONFIGURE TRUE
    LOG_BUILD TRUE
    LOG_OUTPUT_ON_FAILURE TRUE
)
endif()

# --- Kaldi ---
# Kaldi's "conda" mode uses the OpenFst and BLAS found in CONDA_ROOT and reads
# LAPACKE headers from $PREFIX/include. kaldi-0002 keeps the MSVC dllimport
# definitions out of the static libraries.
ExternalProject_Add(kaldi
    DEPENDS openblas openfst
    URL "https://github.com/kaldi-asr/kaldi/archive/${KALDI_COMMIT}.tar.gz"
    URL_HASH SHA256=${KALDI_SHA256}
    DOWNLOAD_DIR "${KALPY_DEPS_DOWNLOAD_DIR}"
    DOWNLOAD_NAME "kaldi-${KALDI_COMMIT}.tar.gz"
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    PATCH_COMMAND ${PATCH_EXECUTABLE} -p1 -i ${PATCHES_DIR}/kaldi-0001-Shared-libraries-on-windows.patch
    COMMAND ${PATCH_EXECUTABLE} -p1 -i ${PATCHES_DIR}/kaldi-0002-Static-libraries-on-windows.patch
    CONFIGURE_COMMAND ${DEPS_ENV} "PREFIX=${PREFIX}"
        ${CMAKE_COMMAND} -S <SOURCE_DIR> -B <BINARY_DIR>
        ${DEPS_CMAKE_ARGS}
        -DCMAKE_INSTALL_LIBDIR=lib
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
