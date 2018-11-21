# -*- coding: future_fstrings -*-

# Copyright 2018 Streamlit Inc. All rights reserved.

"""Tools for working with dicts."""

# Python 2/3 compatibility
from __future__ import print_function, division, unicode_literals, absolute_import
from streamlit.compatibility import setup_2_3_shims
setup_2_3_shims(globals())


def _unflatten_single_dict(flat_dict):
    """Convert a flat dict of key-value pairs to dict tree.

    Example
    -------

        _unflatten_single_dict({
          foo_bar_baz: 123,
          foo_bar_biz: 456,
          x_bonks: 'hi',
        })

        # Returns:
        # {
        #   foo: {
        #     bar: {
        #       baz: 123,
        #       biz: 456,
        #     },
        #   },
        #   x: {
        #     bonks: 'hi'
        #   }
        # }

    Parameters
    ----------
    flat_dict : dict
        A one-level dict where keys are fully-qualified paths separated by
        underscores.

    Returns
    -------
    dict
        A tree made of dicts inside of dicts.

    """
    out = dict()
    for pathstr, v in flat_dict.items():
        path = pathstr.split('_')

        prev_dict = None
        curr_dict = out

        for k in path:
            if k not in curr_dict:
                curr_dict[k] = dict()
            prev_dict = curr_dict
            curr_dict = curr_dict[k]

        prev_dict[k] = v

    return out


def unflatten(flat_dict, encodings=None):
    """Converts a flat dict of key-value pairs to a spec tree.

    Example:
        unflatten({
          foo_bar_baz: 123,
          foo_bar_biz: 456,
          x_bonks: 'hi',
        }, ['x'])

        # Returns:
        # {
        #   foo: {
        #     bar: {
        #       baz: 123,
        #       biz: 456,
        #     },
        #   },
        #   encoding: {  # This gets added automatically
        #     x: {
        #       bonks: 'hi'
        #     }
        #   }
        # }

    Args:
    -----
    flat_dict: dict
        A flat dict where keys are fully-qualified paths separated by
        underscores.

    encodings: set
        Key names that should be automatically moved into the 'encoding' key.

    Returns:
    --------
    A tree made of dicts inside of dicts.
    """
    if encodings is None:
        encodings = set()

    out_dict = _unflatten_single_dict(flat_dict)

    for k, v in list(out_dict.items()):
        # Unflatten child dicts:
        if type(v) in (dict, native_dict):
            v = unflatten(v, encodings)
        elif hasattr(v, '__iter__'):
            for i, child in enumerate(v):
                if type(child) in (dict, native_dict):
                    v[i] = unflatten(child, encodings)

        # Move items into 'encoding' if needed:
        if k in encodings:
            if 'encoding' not in out_dict:
                out_dict['encoding'] = dict()
            out_dict['encoding'][k] = v
            out_dict.pop(k)

    return out_dict
