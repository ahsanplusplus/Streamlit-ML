# -*- coding: utf-8 -*-
# Copyright 2018-2019 Streamlit Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Keras unit test."""

import unittest
from mock import patch

from tensorflow.python.keras.utils import vis_utils
from tensorflow.python.keras.models import Sequential
from tensorflow.python.keras.layers import Conv2D, MaxPooling2D, Dense, Flatten

import streamlit as st


class KerasTest(unittest.TestCase):
    """Test ability to marshall keras models."""

    def test_model(self):
        """Test that it can be called with a model."""
        model = Sequential()
        model.add(Conv2D(10, (5, 5), input_shape=(28, 28, 1), activation='relu'))
        model.add(MaxPooling2D(pool_size=(2, 2)))
        model.add(Flatten())
        model.add(Dense(8, activation='relu'))

        with patch('streamlit.graphviz_chart') as graphviz_chart:
            st.write(model)

            dot = vis_utils.model_to_dot(model)
            graphviz_chart.assert_called_once_with(dot.to_string())
