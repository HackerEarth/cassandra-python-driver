# Copyright 2013-2015 DataStax, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from eventlet import monkey_patch
monkey_patch()

try:
    import unittest2 as unittest
except ImportError:
    import unittest # noqa

from tests.unit.io.utils import submit_and_wait_for_completion
from tests import is_eventlet_monkey_patched


try:
    from cassandra.io.eventletreactor import EventletConnection
except ImportError:
    EventletConnection = None  # noqa


class EventletTimerTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not is_eventlet_monkey_patched():
            raise unittest.SkipTest("Can't test eventlet without monkey patching")
        EventletConnection.initialize_reactor()

    @classmethod
    def tearDownClass(cls):
        if not is_eventlet_monkey_patched():
            return

    def test_multi_timer_validation(self, *args):
        """
        Verify that timer timeouts are honored appropriately
        """
        submit_and_wait_for_completion(self, EventletConnection, 0, 100, 1, 100)
        submit_and_wait_for_completion(self, EventletConnection, 100, 0, -1, 100)
        submit_and_wait_for_completion(self, EventletConnection, 0, 100, 1, 100, True)