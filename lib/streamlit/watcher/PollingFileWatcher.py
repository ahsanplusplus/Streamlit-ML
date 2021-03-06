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

"""A class that watches the file system"""

# Python 2/3 compatibility
from __future__ import print_function, division, unicode_literals, absolute_import
from streamlit.compatibility import setup_2_3_shims
setup_2_3_shims(globals())

from concurrent.futures import ThreadPoolExecutor
import os
import time

from streamlit.watcher import util

from streamlit.logger import get_logger
LOGGER = get_logger(__name__)


_MAX_WORKERS = 4
_POLLING_PERIOD_SECS = 0.2


class PollingFileWatcher(object):
    """Watches a single file on disk via a polling loop"""

    _executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS)

    @staticmethod
    def close_all():
        """Close top-level watcher object.

        This is a no-op, and exists for interface parity with
        EventBasedFileWatcher.
        """
        LOGGER.debug('Watcher closed')

    def __init__(self, file_path, on_file_changed):
        """Constructor.

        Arguments
        ---------
        file_path : str
            Absolute path of the file to watch.

        on_file_changed : callable
            Function to call when the file changes. This function should
            take the changed file's path as a parameter.

        """
        self._file_path = file_path
        self._on_file_changed = on_file_changed

        self._active = True
        self._modification_time = os.stat(self._file_path).st_mtime
        self._md5 = util.calc_md5_with_blocking_retries(self._file_path)
        self._schedule()

    def _schedule(self):
        def task():
            time.sleep(_POLLING_PERIOD_SECS)
            self._check_if_file_changed()

        PollingFileWatcher._executor.submit(task)

    def _check_if_file_changed(self):
        if not self._active:
            # Don't call self._schedule()
            return

        modification_time = os.stat(self._file_path).st_mtime
        if modification_time <= self._modification_time:
            self._schedule()
            return

        self._modification_time = modification_time

        md5 = util.calc_md5_with_blocking_retries(self._file_path)
        if md5 == self._md5:
            self._schedule()
            return

        self._md5 = md5

        LOGGER.debug('Change detected: %s', self._file_path)
        self._on_file_changed(self._file_path)

        self._schedule()

    def close(self):
        """Stop watching the file system."""
        self._active = False
