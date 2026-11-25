# Remove `#define LAPACK_FORTRAN_STRLEN_END` from an installed lapack.h, so that
# LAPACK routines are declared without the hidden Fortran string-length
# arguments, as in the reference LAPACK 3.9.0 headers Kaldi is written against.
#
# Usage: cmake -DFILE=/path/to/lapack.h -P drop-lapack-strlen.cmake
if(NOT DEFINED FILE OR NOT EXISTS "${FILE}")
    message(FATAL_ERROR "FILE must point to an existing lapack.h (got '${FILE}')")
endif()
file(READ "${FILE}" content)
string(REGEX REPLACE "\n#define LAPACK_FORTRAN_STRLEN_END\n" "\n\n" patched "${content}")
if(patched STREQUAL content AND NOT content MATCHES "LAPACK_FORTRAN_STRLEN_END")
    message(FATAL_ERROR "${FILE} does not mention LAPACK_FORTRAN_STRLEN_END: unexpected header")
endif()
file(WRITE "${FILE}" "${patched}")
