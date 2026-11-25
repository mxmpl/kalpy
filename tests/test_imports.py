import pytest


def test_import():
    import _kalpy

    print(_kalpy.__version__)
    import _kalpy.cudamatrix
    import _kalpy.decoder
    import _kalpy.feat
    import _kalpy.fstext
    import _kalpy.gmm
    import _kalpy.hmm
    import _kalpy.ivector
    import _kalpy.lat
    import _kalpy.lm
    import _kalpy.matrix
    import _kalpy.tree
    import _kalpy.util


def test_import_nnet():
    import _kalpy

    if not hasattr(_kalpy, "nnet3"):
        pytest.skip("kalpy was built without KALPY_WITH_NNET")
    import _kalpy.chain
    import _kalpy.kws
    import _kalpy.nnet
    import _kalpy.nnet2
    import _kalpy.nnet3
    import _kalpy.online
    import _kalpy.online2
