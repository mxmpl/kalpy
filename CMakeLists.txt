cmake_minimum_required(VERSION 3.18)
project(_kalpy)

set(CMAKE_CXX_STANDARD 17)

set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_CXX_EXTENSIONS OFF)
option(BUILD_SHARED_LIBS "Build shared libraries" ON)
if(NOT KALDI_ROOT AND DEFINED ENV{KALDI_ROOT})
    set(KALDI_ROOT "$ENV{KALDI_ROOT}")
endif()
if(KALDI_ROOT)
    message(STATUS "Adding KALDI_ROOT directories: ${KALDI_ROOT}")
    set(CMAKE_INCLUDE_PATH "${KALDI_ROOT}/include")
    set(CMAKE_LIBRARY_PATH "${KALDI_ROOT}/lib")
    link_directories("${KALDI_ROOT}/lib")
    include_directories("${KALDI_ROOT}/include")
    include_directories("${KALDI_ROOT}/include/kaldi")
    if (NOT CUDA_TOOLKIT_ROOT_DIR)
        set(CUDA_TOOLKIT_ROOT_DIR "${KALDI_ROOT}")
    endif()

endif()
add_definitions(-DKALDI_NO_PORTAUDIO=1)
add_definitions(-DOPENFST_VER=18400)
if (MSVC)
    find_package(dlfcn-win32 REQUIRED)
    set(CMAKE_DL_LIBS dlfcn-win32::dl)

    #   set(CMAKE_WINDOWS_EXPORT_ALL_SYMBOLS ON)
    add_definitions(-DWIN32_LEAN_AND_MEAN)
    add_definitions(-DNOMINMAX)
    add_definitions(-D_SILENCE_ALL_CXX17_DEPRECATION_WARNINGS)
    add_definitions(-D_USE_MATH_DEFINES)
    add_compile_options(/permissive- /FS /wd4819 /EHsc /bigobj)

    # some warnings related with fst
    add_compile_options(/wd4018 /wd4244 /wd4267 /wd4291 /wd4305)

 elseif(APPLE)
     set(CMAKE_INSTALL_RPATH "@loader_path")
 else()
     set(CMAKE_INSTALL_RPATH "$ORIGIN;$ORIGIN/../lib;$ORIGIN/../../tools/openfst/lib")
endif ()

if(KALDI_ROOT AND NOT MSVC)
    list(APPEND CMAKE_INSTALL_RPATH "${KALDI_ROOT}/lib")
endif()

find_package(CUDAToolkit)

option(KALPY_WITH_NNET "Build bindings for Kaldi's neural network, online decoding and keyword search libraries" ON)
option(KALPY_STATIC_KALDI "Link Kaldi, OpenFst and OpenBLAS statically, keeping only the code the bindings use (for standalone wheels)" OFF)

find_package(pybind11 REQUIRED)
include_directories(extensions)

set(KALPY_SOURCES extensions/_kalpy.cpp
                  extensions/cudamatrix/cudamatrix.cpp
                  extensions/decoder/decoder.cpp
                  extensions/feat/feat.cpp
                  extensions/fstext/fstext.cpp
                  extensions/gmm/gmm.cpp
                  extensions/hmm/hmm.cpp
                  extensions/itf/itf.cpp
                  extensions/ivector/ivector.cpp
                  extensions/lat/lat.cpp
                  extensions/lm/lm.cpp
                  extensions/matrix/matrix.cpp
                  extensions/transform/transform.cpp
                  extensions/tree/tree.cpp
                  extensions/util/util.cpp
                  )
set(KALPY_KALDI_LIBS kaldi-decoder kaldi-lat kaldi-ivector kaldi-lm
                     kaldi-fstext kaldi-feat kaldi-transform kaldi-gmm
                     kaldi-hmm kaldi-tree kaldi-cudamatrix kaldi-util
                     kaldi-matrix kaldi-base
                     )
if(KALPY_WITH_NNET)
    list(APPEND KALPY_SOURCES extensions/chain/chain.cpp
                              extensions/kws/kws.cpp
                              #extensions/rnnlm/rnnlm.cpp
                              extensions/online/online.cpp
                              extensions/online2/online2.cpp
                              extensions/nnet/nnet.cpp
                              extensions/nnet2/nnet2.cpp
                              extensions/nnet3/nnet3.cpp
                              )
    list(PREPEND KALPY_KALDI_LIBS kaldi-online2 kaldi-online kaldi-rnnlm
                                  kaldi-kws kaldi-nnet3 kaldi-chain
                                  kaldi-nnet2 kaldi-nnet
                                  )
endif()

pybind11_add_module(_kalpy ${KALPY_SOURCES})
if(KALPY_WITH_NNET)
    target_compile_definitions(_kalpy PRIVATE KALPY_WITH_NNET)
endif()

if(KALPY_STATIC_KALDI)
    # Everything ends up in _kalpy itself: static libraries (built with
    # -ffunction-sections) let the linker drop the code the bindings never
    # reach, and none of their symbols are exported, so kalpy's OpenFst cannot
    # clash with another copy loaded in the same process (e.g. pynini's).
    find_library(KALPY_OPENBLAS NAMES libopenblas.a REQUIRED)
    find_package(Threads REQUIRED)
    set(KALPY_STATIC_LIBS ${KALPY_KALDI_LIBS} fstscript fst ${KALPY_OPENBLAS})
    if(APPLE)
        target_link_libraries(_kalpy PRIVATE ${KALPY_STATIC_LIBS})
        target_link_options(_kalpy PRIVATE -Wl,-dead_strip
                                           -Wl,-exported_symbol,_PyInit__kalpy)
    else()
        # Static libraries depend on each other in both directions
        target_link_libraries(_kalpy PRIVATE -Wl,--start-group ${KALPY_STATIC_LIBS} -Wl,--end-group)
        target_link_options(_kalpy PRIVATE -Wl,--gc-sections -Wl,--exclude-libs,ALL)
    endif()
    target_link_libraries(_kalpy PRIVATE Threads::Threads ${CMAKE_DL_LIBS} m)
else()
    target_link_libraries(_kalpy PUBLIC ${KALPY_KALDI_LIBS} fst fstscript)
    if (CUDAToolkit_FOUND)
        find_library(KALDI_CUDADECODER kaldi-cudadecoder)
        if(KALDI_CUDADECODER)
           target_link_libraries(_kalpy PUBLIC kaldi-cudadecoder kaldi-cudafeat)
        endif()
    endif()
endif()

if(MSVC)
set_target_properties(_kalpy PROPERTIES
    DEFINE_SYMBOL "KALDI_DLL_IMPORTS"
                "KALDI_CUMATRIX_DLL_IMPORTS"
                "KALDI_UTIL_DLL_IMPORTS")
endif(MSVC)

install(TARGETS _kalpy LIBRARY DESTINATION . RUNTIME DESTINATION .)
