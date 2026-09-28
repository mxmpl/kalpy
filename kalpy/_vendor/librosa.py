"""Audio loading and resampling, vendored from librosa.

This module contains a trimmed-down copy of the audio loading and resampling
routines of `librosa <https://librosa.org/>`_ (version 1.0.0), so that kalpy can
depend on `soundfile` and `soxr` directly rather than pulling in the full
librosa stack (numba, scipy, lazy_loader, ...).

The functions below are adapted from ``librosa/core/audio.py`` and
``librosa/util/utils.py``.  Compared to the originals, the resampling backends
other than `soxr` have been removed, along with the multi-signal mixing
behaviour of :func:`to_mono` that kalpy does not use.  Behaviour for the
supported code paths is unchanged.

Acknowledgments
---------------
librosa is developed by the librosa development team, led by Brian McFee.  If
you use this code in academic work, please cite librosa:

    McFee, Brian, Colin Raffel, Dawen Liang, Daniel P.W. Ellis, Matt McVicar,
    Eric Battenberg, and Oriol Nieto. "librosa: Audio and music signal analysis
    in Python." In Proceedings of the 14th python in science conference,
    pp. 18-25. 2015.

License
-------
librosa is distributed under the ISC license, reproduced in
``LICENSE.librosa.md`` next to this file::

    Copyright (c) 2013--2026, librosa development team.

    Permission to use, copy, modify, and/or distribute this software for any
    purpose with or without fee is hereby granted, provided that the above
    copyright notice and this permission notice appear in all copies.

    THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
    WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
    MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
    ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
    WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
    ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
    OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
"""
from __future__ import annotations

import os
import typing

import numpy as np
import numpy.typing
import soundfile as sf
import soxr

__all__ = ["ParameterError", "fix_length", "load", "resample", "to_mono", "valid_audio"]


class ParameterError(Exception):
    """Exception class for mal-formed inputs"""


def valid_audio(y: np.ndarray) -> bool:
    """
    Validate whether a variable contains valid audio data.

    Parameters
    ----------
    y: :class:`~numpy.ndarray`
        Array to validate

    Returns
    -------
    bool
        True if all tests pass

    Raises
    ------
    ParameterError
        If ``y`` is not a floating-point, finite :class:`~numpy.ndarray` of at
        least one dimension
    """
    if not isinstance(y, np.ndarray):
        raise ParameterError("Audio data must be of type numpy.ndarray")

    if not np.issubdtype(y.dtype, np.floating):
        raise ParameterError("Audio data must be floating-point")

    if y.ndim == 0:
        raise ParameterError(
            f"Audio data must be at least one-dimensional, given y.shape={y.shape}"
        )

    if not np.isfinite(y).all():
        raise ParameterError("Audio buffer is not finite everywhere")

    return True


def fix_length(data: np.ndarray, *, size: int, axis: int = -1, **kwargs) -> np.ndarray:
    """
    Fix the length of an array ``data`` to exactly ``size`` along a target axis.

    If ``data.shape[axis] < size``, pad according to the provided kwargs.
    By default, ``data`` is padded with trailing zeros.

    Parameters
    ----------
    data: :class:`~numpy.ndarray`
        Array to be length-adjusted
    size: int
        Desired length of the array
    axis: int
        Axis along which to fix length
    **kwargs
        Additional keyword arguments to :func:`numpy.pad`

    Returns
    -------
    :class:`~numpy.ndarray`
        ``data`` either trimmed or padded to length ``size`` along the
        specified axis
    """
    kwargs.setdefault("mode", "constant")

    n = data.shape[axis]

    if n > size:
        slices = [slice(None)] * data.ndim
        slices[axis] = slice(0, size)
        return data[tuple(slices)]

    elif n < size:
        lengths = [(0, 0)] * data.ndim
        lengths[axis] = (0, size - n)
        return np.pad(data, lengths, **kwargs)

    return data


def to_mono(y: np.ndarray) -> np.ndarray:
    """
    Convert an audio signal to mono by averaging samples across channels.

    Parameters
    ----------
    y: :class:`~numpy.ndarray`
        Audio signal of shape ``(..., n)``, mono or multi-channel

    Returns
    -------
    :class:`~numpy.ndarray`
        Signal of shape ``(n,)`` averaged over all leading axes
    """
    valid_audio(y)

    if y.ndim == 1:
        return y

    return np.mean(y, axis=tuple(range(y.ndim - 1)))


def resample(
    y: np.ndarray,
    *,
    orig_sr: float,
    target_sr: float,
    res_type: str = "soxr_hq",
    fix: bool = True,
    scale: bool = False,
    axis: int = -1,
    **kwargs,
) -> np.ndarray:
    """
    Resample a time series from ``orig_sr`` to ``target_sr``.

    Parameters
    ----------
    y: :class:`~numpy.ndarray`
        Audio time series, with ``n`` samples along the specified axis
    orig_sr: float
        Original sampling rate of ``y``
    target_sr: float
        Target sampling rate
    res_type: str
        Resampling quality, one of ``soxr_vhq``, ``soxr_hq``, ``soxr_mq``,
        ``soxr_lq`` or ``soxr_qq``, defaults to ``soxr_hq``
    fix: bool
        Adjust the length of the resampled signal to be of size exactly
        ``ceil(target_sr * len(y) / orig_sr)``, defaults to True
    scale: bool
        Scale the resampled signal so that ``y`` and the output have
        approximately equal total energy, defaults to False
    axis: int
        The target axis along which to resample, defaults to the trailing axis
    **kwargs
        If ``fix=True``, additional keyword arguments to pass to
        :func:`fix_length`

    Returns
    -------
    :class:`~numpy.ndarray`
        ``y`` resampled from ``orig_sr`` to ``target_sr`` along the target axis

    Raises
    ------
    ParameterError
        If ``res_type`` is not one of the `soxr` quality settings
    """
    # First, validate the audio buffer
    valid_audio(y)

    if orig_sr == target_sr:
        return y

    ratio = float(target_sr) / orig_sr

    n_samples = int(np.ceil(y.shape[axis] * ratio))

    if not res_type.startswith("soxr"):
        raise ParameterError(
            f"Unsupported res_type={res_type}, only soxr resampling is supported"
        )

    # Use numpy to vectorize the resampler along the target axis
    # This is because soxr does not support ndim>2 generally.
    y_hat = np.apply_along_axis(
        soxr.resample,
        axis=axis,
        arr=y,
        in_rate=orig_sr,
        out_rate=target_sr,
        quality=res_type,
    )

    if fix:
        y_hat = fix_length(y_hat, size=n_samples, axis=axis, **kwargs)

    if scale:
        y_hat /= np.sqrt(ratio)

    # Match dtypes
    return np.asarray(y_hat, dtype=y.dtype)


def load(
    path: typing.Union[str, int, os.PathLike, sf.SoundFile, typing.BinaryIO],
    *,
    sr: typing.Optional[float] = 22050,
    mono: bool = True,
    offset: float = 0.0,
    duration: typing.Optional[float] = None,
    dtype: np.typing.DTypeLike = np.float32,
    res_type: str = "soxr_hq",
) -> typing.Tuple[np.ndarray, float]:
    """
    Load an audio file as a floating point time series.

    Audio will be automatically resampled to the given rate.  To preserve the
    native sampling rate of the file, use ``sr=None``.

    Parameters
    ----------
    path: str, int, :class:`~pathlib.Path`, :class:`soundfile.SoundFile` or file-like object
        Path to the input file.  Any codec supported by `soundfile` will work,
        as will an open file descriptor or an existing
        :class:`soundfile.SoundFile` object.
    sr: float, optional
        Target sampling rate, ``None`` uses the native sampling rate
    mono: bool
        Convert signal to mono, defaults to True
    offset: float
        Start reading after this time (in seconds).  If negative, it will be
        interpreted relative to the end of the file.
    duration: float, optional
        Only load up to this much audio (in seconds)
    dtype: numeric type
        Data type of the returned waveform
    res_type: str
        Resampling quality, see :func:`resample`

    Returns
    -------
    :class:`~numpy.ndarray`
        Audio time series of shape ``(n,)`` or ``(..., n)``
    float
        Sampling rate of the returned waveform
    """
    y, sr_native = _soundfile_load(path, offset, duration, dtype)

    # Final cleanup for dtype and contiguity
    if mono:
        y = to_mono(y)

    if sr is not None:
        y = resample(y, orig_sr=sr_native, target_sr=sr, res_type=res_type)

    else:
        sr = sr_native

    return y, sr


def _soundfile_load(path, offset, duration, dtype):
    """Load an audio buffer using soundfile."""
    if isinstance(path, sf.SoundFile):
        # If the user passed an existing soundfile object,
        # we can use it directly
        context = path
    else:
        # Otherwise, create the soundfile object
        context = sf.SoundFile(path)

    with context as sf_desc:
        sr_native = sf_desc.samplerate
        if offset != 0:
            if offset > 0:
                # Seek to the start of the target read
                sf_desc.seek(int(offset * sr_native))
            else:
                sf_desc.seek(-int(abs(offset) * sr_native), whence=sf.SEEK_END)

        if duration is not None:
            frame_duration = int(duration * sr_native)
        else:
            frame_duration = -1

        # Load the target number of frames, and transpose to match librosa form
        y = sf_desc.read(frames=frame_duration, dtype=dtype, always_2d=False).T

    return y, sr_native
