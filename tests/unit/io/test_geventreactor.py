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

import gevent.monkey
# gevent.monkey.patch_all()
from gevent_utils import gevent_un_patch_all

try:
    import unittest2 as unittest
except ImportError:
    import unittest # noqa

from tests.unit.io.utils import submit_and_wait_for_completion
from tests import is_gevent_monkey_patched


try:
    from cassandra.io.geventreactor import GeventConnection
except ImportError:
    GeventConnection = None  # noqa


class GeventTimerTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):

        if not is_gevent_monkey_patched():
            gevent.monkey.patch_all()
        if not is_gevent_monkey_patched():
            raise unittest.SkipTest("Can't test gevent without monkey patching")

        GeventConnection.initialize_reactor()

    @classmethod
    def tearDownClass(cls):
        if is_gevent_monkey_patched():
            gevent_un_patch_all()
        if is_gevent_monkey_patched():
            print "Error un patching gevent this is bad"

    def test_multi_timer_validation(self, *args):
        submit_and_wait_for_completion(self, GeventConnection, 0, 100, 1, 100)
        submit_and_wait_for_completion(self, GeventConnection, 100, 0, -1, 100)
        submit_and_wait_for_completion(self, GeventConnection, 0, 100, 1, 100, True)