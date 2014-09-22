# Copyright 2014 IBM Corp.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock
import testtools

import trove.common.cfg as cfg
import trove.tests.fakes.conf as fake_conf

from trove.cmd import conductor as conductor_cmd
from trove.cmd import common as common_cmd
from trove.openstack.common import service as os_service

CONF = cfg.CONF
TROVE_UT = 'trove.tests.unittests'


def mocked_conf(manager):
    return fake_conf.FakeConf({
        'conductor_queue': 'conductor',
        'conductor_manager': manager,
        'trove_conductor_workers': 1,
        'host': 'mockhost',
        'report_interval': 1})


class NoopManager(object):
    pass


class ConductorConfTests(testtools.TestCase):
    def setUp(self):
        super(ConductorConfTests, self).setUp()

    def tearDown(self):
        super(ConductorConfTests, self).tearDown()

    def _test_manager(self, conf, rt_mgr_name):
        def mock_launch(server, workers):
            qualified_mgr = "%s.%s" % (server.manager_impl.__module__,
                                       server.manager_impl.__class__.__name__)
            self.assertEqual(rt_mgr_name, qualified_mgr, "Invalid manager")
            return mock.MagicMock()

        os_service.launch = mock_launch
        common_cmd.initialize = mock.MagicMock(return_value=conf)
        conductor_cmd.main()

    def test_user_defined_manager(self):
        qualified_mgr = TROVE_UT + ".conductor.test_conf.NoopManager"
        self._test_manager(mocked_conf(qualified_mgr), qualified_mgr)

    def test_default_manager(self):
        qualified_mgr = "trove.conductor.manager.Manager"
        self._test_manager(CONF, qualified_mgr)

    def test_invalid_manager(self):
        self.assertRaises(ImportError, self._test_manager,
                          mocked_conf('foo.bar.MissingMgr'),
                          'foo.bar.MissingMgr')
