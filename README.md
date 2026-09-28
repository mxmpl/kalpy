# kalpy
Pybind11 bindings for Kaldi for use in [Montreal Forced Aligner](montreal-forced-aligner.readthedocs.io/).

## Installation

Kalpy depends on Kaldi being built as shared libraries, and the easiest way to install is via conda-forge:

```
conda install -c conda-forge kalpy
```

Kalpy is also available on PyPI as `kalpy-kaldi`. The wheels for Linux (x86_64, aarch64) and macOS (x86_64, arm64) bundle Kaldi, OpenFst and OpenBLAS, so nothing else needs to be installed. To keep them small, they leave out the bindings to Kaldi's neural network, online decoding and keyword search libraries (`_kalpy.nnet`, `nnet2`, `nnet3`, `chain`, `online`, `online2`, `kws`), which the conda-forge package and source builds include:

```
pip install kalpy-kaldi
```

Building FSTs (lexicons, training and decoding graphs) additionally requires [pynini](https://github.com/kylebgorman/pynini), which publishes wheels for Linux x86_64 only: use `pip install "kalpy-kaldi[fst]"` there, or `conda install -c conda-forge pynini` elsewhere.

On other platforms, pip builds kalpy from source against existing Kaldi shared libraries, located with the `KALDI_ROOT` environment variable (for instance a conda environment with `conda install -c conda-forge kaldi`):

```
export KALDI_ROOT=/path/to/conda/environment
pip install kalpy-kaldi
```

Source builds can leave out the same bindings with `pip install kalpy-kaldi --config-settings=cmake.define.KALPY_WITH_NNET=OFF`.

## Usage

Two libraries are installed, `_kalpy` which contains low level bindings conforming to the original C++ style, and `kalpy` which is a more pythonic interface for higher level operations.  The `kalpy` package is under heavy development and expansion to expose more functionality.
