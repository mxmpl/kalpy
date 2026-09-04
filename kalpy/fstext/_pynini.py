"""Access to the optional pynini dependency"""
from __future__ import annotations

import typing

_ERROR_MESSAGE = """\
{module} requires pynini, an optional dependency of kalpy.

pynini publishes wheels for Linux x86_64 only, so:

  * Linux x86_64:  pip install "kalpy-kaldi[fst]"
  * anything else: conda install -c conda-forge pynini

Everything in kalpy that does not build FSTs (features, CMVN, GMM alignment and
decoding from pre-built graphs) works without it.\
"""


def require_pynini(module: str) -> typing.Tuple[typing.Any, typing.Any]:
    """
    Import pynini and pywrapfst, raising an informative error if they are missing

    Parameters
    ----------
    module: str
        Name of the kalpy module requiring pynini, used in the error message

    Returns
    -------
    tuple[module, module]
        The :mod:`pynini` and :mod:`pywrapfst` modules

    Raises
    ------
    ImportError
        If pynini is not installed
    """
    try:
        import pynini
        import pywrapfst
    except ImportError as e:
        raise ImportError(_ERROR_MESSAGE.format(module=module)) from e
    return pynini, pywrapfst
