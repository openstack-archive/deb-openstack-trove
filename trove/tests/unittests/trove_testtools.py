# Copyright 2015 Tesora Inc.
# All Rights Reserved.
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

import abc
import inspect
import mock
import os
import sys
import testtools

from trove.common import cfg
from trove.common.context import TroveContext
from trove.common.notification import DBaaSAPINotification
from trove.tests import root_logger


def is_bool(val):
    return str(val).lower() in ['true', '1', 't', 'y', 'yes', 'on', 'set']


def patch_notifier(test_case):
    notification_notify = mock.patch.object(
        DBaaSAPINotification, "_notify")
    notification_notify.start()
    test_case.addCleanup(notification_notify.stop)


class TroveTestNotification(DBaaSAPINotification):

    @abc.abstractmethod
    def event_type(self):
        return 'test_notification'

    @abc.abstractmethod
    def required_start_traits(self):
        return []


class TroveTestContext(TroveContext):

    def __init__(self, test_case, **kwargs):
        super(TroveTestContext, self).__init__(**kwargs)
        self.notification = TroveTestNotification(
            self, request_id='req_id', flavor_id='7')
        self.notification.server_type = 'api'
        patch_notifier(test_case)


class TestCase(testtools.TestCase):
    """Base class of Trove unit tests.
    Integrates automatic dangling mock detection.
    """

    _NEWLINE = '\n'

    # Number of nested levels to examine when searching for mocks.
    # Higher setting will potentially uncover more dangling objects,
    # at the cost of increased scanning time.
    _max_recursion_depth = int(os.getenv(
        'TROVE_TESTS_UNMOCK_RECURSION_DEPTH', 2))
    # Should we skip the remaining tests after the first failure.
    _fail_fast = is_bool(os.getenv(
        'TROVE_TESTS_UNMOCK_FAIL_FAST', False))
    # Should we report only unique dangling mock references.
    _only_unique = is_bool(os.getenv(
        'TROVE_TESTS_UNMOCK_ONLY_UNIQUE', True))

    @classmethod
    def setUpClass(cls):
        super(TestCase, cls).setUpClass()

        cls._dangling_mocks = set()

        root_logger.DefaultRootLogger(enable_backtrace=False)

    @classmethod
    def tearDownClass(cls):
        cls._assert_modules_unmocked()
        super(TestCase, cls).tearDownClass()

    def setUp(self):
        if self.__class__._fail_fast and self.__class__._dangling_mocks:
            self.skipTest("This test suite already has dangling mock "
                          "references from a previous test case.")

        super(TestCase, self).setUp()
        root_logger.DefaultRootHandler.set_info(self.id())

        # Default manager used by all unittsest unless explicitly overriden.
        self.patch_datastore_manager('mysql')

    def tearDown(self):
        # yes, this is gross and not thread aware.
        # but the only way to make it thread aware would require that
        # we single thread all testing
        root_logger.DefaultRootHandler.set_info(info=None)
        super(TestCase, self).tearDown()

    @classmethod
    def _assert_modules_unmocked(cls):
        """Check that all members of loaded modules are currently unmocked.
        """
        new_mocks = cls._find_mock_refs()
        if cls._only_unique:
            # Remove mock references that have already been reported once in
            # this test suite (probably defined in setUp()).
            new_mocks.difference_update(cls._dangling_mocks)

        cls._dangling_mocks.update(new_mocks)

        if new_mocks:
            messages = ["Member '%s' needs to be unmocked." % item[0]
                        for item in new_mocks]
            raise Exception(cls._NEWLINE + cls._NEWLINE.join(messages))

    @classmethod
    def _find_mock_refs(cls):
        discovered_mocks = set()
        for module_name, module in cls._get_loaded_modules().items():
            cls._find_mocks(module_name, module, discovered_mocks, 1)

        return discovered_mocks

    @classmethod
    def _find_mocks(cls, parent_name, parent, container, depth):
        """Search for mock members in the parent object.
        Descend into class types.
        """
        if depth <= cls._max_recursion_depth:
            try:
                if isinstance(parent, mock.Mock):
                    # Add just the parent if it's a mock itself.
                    container.add((parent_name, parent))
                else:
                    # Add all mocked members of the parent.
                    for member_name, member in inspect.getmembers(parent):
                        full_name = '%s.%s' % (parent_name, member_name)
                        if isinstance(member, mock.Mock):
                            container.add((full_name, member))
                        elif inspect.isclass(member):
                            cls._find_mocks(
                                full_name, member, container, depth + 1)
            except ImportError:
                pass  # Module cannot be imported - ignore it.
            except RuntimeError:
                # Something else went wrong when probing the class member.
                # See: https://bugs.launchpad.net/trove/+bug/1524918
                pass

    @classmethod
    def _get_loaded_modules(cls):
        return {name: obj for name, obj in sys.modules.items() if obj}

    def patch_datastore_manager(self, manager_name):
        return self.patch_conf_property('datastore_manager', manager_name)

    def patch_conf_property(self, property_name, value, section=None):
        target = cfg.CONF
        if section:
            target = target.get(section)
        conf_patcher = mock.patch.object(
            target, property_name,
            new_callable=mock.PropertyMock(return_value=value))
        self.addCleanup(conf_patcher.stop)
        return conf_patcher.start()
