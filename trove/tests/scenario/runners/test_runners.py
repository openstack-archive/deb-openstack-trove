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

import datetime
import os
import time as timer

from oslo_config.cfg import NoSuchOptError
from proboscis import asserts
import swiftclient
from troveclient.compat import exceptions

from trove.common import cfg
from trove.common import exception
from trove.common.strategies.strategy import Strategy
from trove.common import utils
from trove.common.utils import poll_until, build_polling_task
from trove.tests.config import CONFIG
from trove.tests.util.check import AttrCheck
from trove.tests.util import create_dbaas_client
from trove.tests.util import create_nova_client
from trove.tests.util.users import Requirements

CONF = cfg.CONF

TEST_RUNNERS_NS = 'trove.tests.scenario.runners'
TEST_HELPERS_NS = 'trove.tests.scenario.helpers'
TEST_HELPER_MODULE_NAME = 'test_helper'
TEST_HELPER_BASE_NAME = 'TestHelper'


class RunnerFactory(object):

    _test_runner = None
    _runner_ns = None
    _runner_cls = None

    @classmethod
    def instance(cls):
        """Returns the current instance of the runner, or creates a new
        one if none exists. This is useful to have multiple 'group' classes
        use the same runner so that state is maintained.
        """
        if not cls._test_runner:
            cls._test_runner = cls.create()
        return cls._test_runner

    @classmethod
    def create(cls):
        """Returns a new instance of the runner. Tests that require a 'fresh'
        runner (typically from a different 'group') can call this.
        """
        return cls._get_runner(cls._runner_ns, cls._runner_cls)

    @classmethod
    def _get_runner(cls, runner_module_name, runner_base_name,
                    *args, **kwargs):
        class_prefix = cls._get_test_datastore()
        runner_cls = cls._load_dynamic_class(
            runner_module_name, class_prefix, runner_base_name,
            TEST_RUNNERS_NS)
        runner = runner_cls(*args, **kwargs)
        runner._test_helper = cls._get_helper(runner.report)
        return runner

    @classmethod
    def _get_helper(cls, report):
        class_prefix = cls._get_test_datastore()
        helper_cls = cls._load_dynamic_class(
            TEST_HELPER_MODULE_NAME, class_prefix,
            TEST_HELPER_BASE_NAME, TEST_HELPERS_NS)
        return helper_cls(
            cls._build_class_name(class_prefix,
                                  TEST_HELPER_BASE_NAME, strip_test=True),
            report)

    @classmethod
    def _get_test_datastore(cls):
        return CONFIG.dbaas_datastore

    @classmethod
    def _load_dynamic_class(cls, module_name, class_prefix, base_name,
                            namespace):
        """Try to load a datastore specific class if it exists; use the
        default otherwise.
        """
        # This is for overridden Runner classes
        impl = cls._build_class_path(module_name, class_prefix, base_name)
        clazz = cls._load_class('runner', impl, namespace)

        if not clazz:
            # This is for overridden Helper classes
            module = module_name.replace('test', class_prefix.lower())
            impl = cls._build_class_path(
                module, class_prefix, base_name, strip_test=True)
            clazz = cls._load_class('helper', impl, namespace)

        if not clazz:
            # Just import the base class
            impl = cls._build_class_path(module_name, '', base_name)
            clazz = cls._load_class(None, impl, namespace)

        return clazz

    @classmethod
    def _load_class(cls, load_type, impl, namespace):
        clazz = None
        if not load_type or load_type in impl.lower():
            try:
                clazz = Strategy.get_strategy(impl, namespace)
            except ImportError as ie:
                # Only fail silently if it's something we expect,
                # such as a missing override class.  Anything else
                # shouldn't be suppressed.
                l_msg = ie.message.lower()
                if load_type not in l_msg or (
                        'no module named' not in l_msg and
                        'cannot be found' not in l_msg):
                    raise
        return clazz

    @classmethod
    def _build_class_path(cls, module_name, class_prefix, class_base,
                          strip_test=False):
        class_name = cls._build_class_name(
            class_prefix, class_base, strip_test)
        return '%s.%s' % (module_name, class_name)

    @classmethod
    def _build_class_name(cls, class_prefix, base_name, strip_test=False):
        base = (base_name.replace('Test', '') if strip_test else base_name)
        return '%s%s' % (class_prefix.capitalize(), base)


class InstanceTestInfo(object):
    """Stores new instance information used by dependent tests."""

    def __init__(self):
        self.id = None  # The ID of the instance in the database.
        self.name = None  # Test name, generated each test run.
        self.dbaas_flavor_href = None  # The flavor of the instance.
        self.dbaas_datastore = None  # The datastore id
        self.dbaas_datastore_version = None  # The datastore version id
        self.volume_size = None  # The size of volume the instance will have.
        self.volume = None  # The volume the instance will have.
        self.nics = None  # The dict of type/id for nics used on the intance.
        self.user = None  # The user instance who owns the instance.
        self.users = None  # The users created on the instance.
        self.databases = None  # The databases created on the instance.


class TestRunner(object):

    """
    Base class for all 'Runner' classes.

    The Runner classes are those that actually do the work.  The 'Group'
    classes are set up with decorators that control how the tests flow,
    and are used to organized the tests - however they are typically set up
    to just call a corresponding method in a Runner class.

    A Runner class can be overridden if a particular set of tests
    needs to have DataStore specific coding.  The corresponding Group
    class will try to first load a DataStore specific class, and then fall
    back to the generic one if need be.  For example,
    the NegativeClusterActionsGroup class specifies a runner_base_name of
    NegativeClusterActionsRunner.  If the manager of the default
    datastore is mongodb, then the MongodbNegativeClusterActionsRunner is
    used instead.  The prefix is created by capitalizing the name of the
    manager - overriding classes *must* follow this naming convention
    to be automatically used.  The main assumption made here is that
    if a manager is used for different datastore versions, then the
    overriding runner should also be valid for the same datastore versions.
    """

    USE_INSTANCE_ID_FLAG = 'TESTS_USE_INSTANCE_ID'
    DO_NOT_DELETE_INSTANCE_FLAG = 'TESTS_DO_NOT_DELETE_INSTANCE'

    VOLUME_SUPPORT = CONFIG.get('trove_volume_support', True)
    EPHEMERAL_SUPPORT = not VOLUME_SUPPORT and CONFIG.get('device_path', None)
    ROOT_PARTITION = not (VOLUME_SUPPORT or CONFIG.get('device_path', None))

    GUEST_CAST_WAIT_TIMEOUT_SEC = 60

    # Here's where the info for the 'main' test instance goes
    instance_info = InstanceTestInfo()
    report = CONFIG.get_report()

    def __init__(self, sleep_time=10, timeout=1200):
        self.def_sleep_time = sleep_time
        self.def_timeout = timeout

        self.instance_info.name = "TEST_" + datetime.datetime.strftime(
            datetime.datetime.now(), '%Y_%m_%d__%H_%M_%S')
        self.instance_info.dbaas_datastore = CONFIG.dbaas_datastore
        self.instance_info.dbaas_datastore_version = (
            CONFIG.dbaas_datastore_version)
        self.instance_info.user = CONFIG.users.find_user_by_name('alt_demo')
        if self.VOLUME_SUPPORT:
            self.instance_info.volume_size = CONFIG.get('trove_volume_size', 1)
            self.instance_info.volume = {
                'size': self.instance_info.volume_size}
        else:
            self.instance_info.volume_size = None
            self.instance_info.volume = None

        self._auth_client = None
        self._unauth_client = None
        self._admin_client = None
        self._swift_client = None
        self._nova_client = None
        self._test_helper = None
        self._servers = {}

    @classmethod
    def fail(cls, message):
        asserts.fail(message)

    @classmethod
    def assert_is_sublist(cls, sub_list, full_list, message=None):
        if not message:
            message = 'Unexpected sublist'
        try:
            message += ": sub_list '%s' (full_list '%s')." % (
                sub_list, full_list)
        except TypeError:
            pass
        return cls.assert_true(set(sub_list).issubset(full_list), message)

    @classmethod
    def assert_unique(cls, iterable, message=None):
        """Assert that a given iterable contains only unique elements.
        """
        cls.assert_equal(len(iterable), len(set(iterable)), message)

    @classmethod
    def assert_true(cls, condition, message=None):
        asserts.assert_true(condition, message=message)

    @classmethod
    def assert_false(cls, condition, message=None):
        asserts.assert_false(condition, message=message)

    @classmethod
    def assert_is_none(cls, value, message=None):
        asserts.assert_is_none(value, message=message)

    @classmethod
    def assert_is_not_none(cls, value, message=None):
        asserts.assert_is_not_none(value, message=message)

    @classmethod
    def assert_list_elements_equal(cls, expected, actual, message=None):
        """Assert that two lists contain same elements
        (with same multiplicities) ignoring the element order.
        """
        return cls.assert_equal(sorted(expected), sorted(actual), message)

    @classmethod
    def assert_equal(cls, expected, actual, message=None):
        if not message:
            message = 'Unexpected value'
        try:
            message += ": '%s' (expected '%s')." % (actual, expected)
        except TypeError:
            pass

        asserts.assert_equal(expected, actual, message=message)

    @classmethod
    def assert_not_equal(cls, expected, actual, message=None):
        if not message:
            message = 'Expected different value than'
        try:
            message += ": '%s'." % expected
        except TypeError:
            pass

        asserts.assert_not_equal(expected, actual, message=message)

    @property
    def test_helper(self):
        return self._test_helper

    @test_helper.setter
    def test_helper(self, test_helper):
        self._test_helper = test_helper

    @property
    def auth_client(self):
        if not self._auth_client:
            self._auth_client = self._create_authorized_client()
        return self._auth_client

    def _create_authorized_client(self):
        """Create a client from the normal 'authorized' user."""
        return create_dbaas_client(self.instance_info.user)

    @property
    def unauth_client(self):
        if not self._unauth_client:
            self._unauth_client = self._create_unauthorized_client()
        return self._unauth_client

    def _create_unauthorized_client(self):
        """Create a client from a different 'unauthorized' user
        to facilitate negative testing.
        """
        requirements = Requirements(is_admin=False)
        other_user = CONFIG.users.find_user(
            requirements, black_list=[self.instance_info.user.auth_user])
        return create_dbaas_client(other_user)

    @property
    def admin_client(self):
        if not self._admin_client:
            self._admin_client = self._create_admin_client()
        return self._admin_client

    def _create_admin_client(self):
        """Create a client from an admin user."""
        requirements = Requirements(is_admin=True, services=["swift"])
        admin_user = CONFIG.users.find_user(requirements)
        return create_dbaas_client(admin_user)

    @property
    def swift_client(self):
        if not self._swift_client:
            self._swift_client = self._create_swift_client()
        return self._swift_client

    def _create_swift_client(self):
        """Create a swift client from the admin user details."""
        requirements = Requirements(is_admin=True, services=["swift"])
        user = CONFIG.users.find_user(requirements)
        os_options = {'region_name': CONFIG.trove_client_region_name}
        return swiftclient.client.Connection(
            authurl=CONFIG.nova_client['auth_url'],
            user=user.auth_user,
            key=user.auth_key,
            tenant_name=user.tenant,
            auth_version='2.0',
            os_options=os_options)

    @property
    def nova_client(self):
        if not self._nova_client:
            self._nova_client = create_nova_client(self.instance_info.user)
        return self._nova_client

    def get_client_tenant(self, client):
        tenant_name = client.real_client.client.tenant
        service_url = client.real_client.client.service_url
        su_parts = service_url.split('/')
        tenant_id = su_parts[-1]
        return tenant_name, tenant_id

    def assert_raises(self, expected_exception, expected_http_code,
                      client_cmd, *cmd_args, **cmd_kwargs):
        asserts.assert_raises(expected_exception, client_cmd,
                              *cmd_args, **cmd_kwargs)

        self.assert_client_code(expected_http_code)

    def get_datastore_config_property(self, name, datastore=None):
        """Get a Trove configuration property for a given datastore.
        Use the current instance's datastore if None.
        """
        try:
            datastore = datastore or self.instance_info.dbaas_datastore
            return CONF.get(datastore).get(name)
        except NoSuchOptError:
            return CONF.get(name)

    @property
    def is_using_existing_instance(self):
        return TestRunner.using_existing_instance()

    @staticmethod
    def using_existing_instance():
        return TestRunner.has_env_flag(TestRunner.USE_INSTANCE_ID_FLAG)

    @staticmethod
    def has_env_flag(flag_name):
        """Return whether a given flag was set."""
        return os.environ.get(flag_name, None) is not None

    def get_existing_instance(self):
        if self.is_using_existing_instance:
            instance_id = os.environ.get(self.USE_INSTANCE_ID_FLAG)
            return self.get_instance(instance_id)

        return None

    @property
    def has_do_not_delete_instance(self):
        return self.has_env_flag(self.DO_NOT_DELETE_INSTANCE_FLAG)

    def assert_instance_action(
            self, instance_ids, expected_states, expected_http_code=None):
        self.assert_client_code(expected_http_code)
        if expected_states:
            self.assert_all_instance_states(
                instance_ids if utils.is_collection(instance_ids)
                else [instance_ids], expected_states)

    def assert_client_code(self, expected_http_code, client=None):
        if expected_http_code is not None:
            client = client or self.auth_client
            self.assert_equal(expected_http_code, client.last_http_code,
                              "Unexpected client status code")

    def assert_all_instance_states(self, instance_ids, expected_states,
                                   fast_fail_status=None,
                                   require_all_states=False):
        self.report.log("Waiting for states (%s) for instances: %s" %
                        (expected_states, instance_ids))

        def _make_fn(inst_id):
            return lambda: self._assert_instance_states(
                inst_id, expected_states,
                fast_fail_status=fast_fail_status,
                require_all_states=require_all_states)

        tasks = [
            build_polling_task(
                _make_fn(instance_id),
                sleep_time=self.def_sleep_time,
                time_out=self.def_timeout) for instance_id in instance_ids]
        poll_until(lambda: all(poll_task.ready() for poll_task in tasks),
                   sleep_time=self.def_sleep_time, time_out=self.def_timeout)

        for task in tasks:
            if task.has_result():
                self.assert_true(
                    task.poll_result(),
                    "Some instances failed to acquire all expected states.")
            elif task.has_exception():
                self.fail(str(task.poll_exception()))

    def _assert_instance_states(self, instance_id, expected_states,
                                fast_fail_status=None,
                                require_all_states=False):
        """Keep polling for the expected instance states until the instance
        acquires either the last or fast-fail state.

        If the instance state does not match the state expected at the time of
        polling (and 'require_all_states' is not set) the code assumes the
        instance had already acquired before and moves to the next expected
        state.
        """

        self.report.log("Waiting for states (%s) for instance: %s" %
                        (expected_states, instance_id))

        if fast_fail_status is None:
            fast_fail_status = ['ERROR', 'FAILED']
        found = False
        for status in expected_states:
            if require_all_states or found or self._has_status(
                    instance_id, status, fast_fail_status=fast_fail_status):
                found = True
                start_time = timer.time()
                try:
                    poll_until(lambda: self._has_status(
                        instance_id, status,
                        fast_fail_status=fast_fail_status),
                        sleep_time=self.def_sleep_time,
                        time_out=self.def_timeout)
                    self.report.log("Instance '%s' has gone '%s' in %s." %
                                    (instance_id, status,
                                     self._time_since(start_time)))
                except exception.PollTimeOut:
                    self.report.log(
                        "Status of instance '%s' did not change to '%s' "
                        "after %s."
                        % (instance_id, status, self._time_since(start_time)))
                    return False
            else:
                self.report.log(
                    "Instance state was not '%s', moving to the next expected "
                    "state." % status)

        return found

    def _time_since(self, start_time):
        return '%.1fs' % (timer.time() - start_time)

    def assert_all_gone(self, instance_ids, expected_last_status):
        self._wait_all_deleted(instance_ids
                               if utils.is_collection(instance_ids)
                               else [instance_ids], expected_last_status)

    def assert_pagination_match(
            self, list_page, full_list, start_idx, end_idx):
        self.assert_equal(full_list[start_idx:end_idx], list(list_page),
                          "List page does not match the expected full "
                          "list section.")

    def _wait_all_deleted(self, instance_ids, expected_last_status):
        self.report.log("Waiting for instances to be gone: %s (status %s)" %
                        (instance_ids, expected_last_status))

        def _make_fn(inst_id):
            return lambda: self._wait_for_delete(inst_id, expected_last_status)

        tasks = [
            build_polling_task(
                _make_fn(instance_id),
                sleep_time=self.def_sleep_time,
                time_out=self.def_timeout) for instance_id in instance_ids]
        poll_until(lambda: all(poll_task.ready() for poll_task in tasks),
                   sleep_time=self.def_sleep_time, time_out=self.def_timeout)

        for task in tasks:
            if task.has_result():
                self.assert_true(
                    task.poll_result(),
                    "Some instances were not removed.")
            elif task.has_exception():
                self.fail(str(task.poll_exception()))

    def _wait_for_delete(self, instance_id, expected_last_status):
        self.report.log("Waiting for instance to be gone: %s (status %s)" %
                        (instance_id, expected_last_status))
        start_time = timer.time()
        try:
            self._poll_while(instance_id, expected_last_status,
                             sleep_time=self.def_sleep_time,
                             time_out=self.def_timeout)
        except exceptions.NotFound:
            self.report.log("Instance was removed in %s." %
                            self._time_since(start_time))
            return True
        except exception.PollTimeOut:
            self.report.log(
                "Instance '%s' still existed after %s."
                % (instance_id, self._time_since(start_time)))

        return False

    def _poll_while(self, instance_id, expected_status,
                    sleep_time=1, time_out=None):
        poll_until(lambda: not self._has_status(instance_id, expected_status),
                   sleep_time=sleep_time, time_out=time_out)

    def _has_status(self, instance_id, status, fast_fail_status=None):
        fast_fail_status = fast_fail_status or []
        instance = self.get_instance(instance_id)
        self.report.log("Polling instance '%s' for state '%s', was '%s'."
                        % (instance_id, status, instance.status))
        if instance.status in fast_fail_status:
            raise RuntimeError("Instance '%s' acquired a fast-fail status: %s"
                               % (instance_id, instance.status))
        return instance.status == status

    def get_server(self, instance_id):
        server = None
        if instance_id in self._servers:
            server = self._servers[instance_id]
        else:
            instance = self.get_instance(instance_id)
            self.report.log("Getting server for instance: %s" % instance)
            for nova_server in self.nova_client.servers.list():
                if str(nova_server.name) == instance.name:
                    server = nova_server
                    break
            if server:
                self._servers[instance_id] = server
        return server

    def assert_server_group_exists(self, instance_id):
        """Check that the Nova instance associated with instance_id
        belongs to a server group, and return the id.
        """
        server = self.get_server(instance_id)
        self.assert_is_not_none(server, "Could not find Nova server for '%s'" %
                                instance_id)
        server_group = None
        server_groups = self.nova_client.server_groups.list()
        for sg in server_groups:
            if server.id in sg.members:
                server_group = sg
                break
        if server_group is None:
            self.fail("Could not find server group for Nova instance %s" %
                      server.id)
        return server_group.id

    def assert_server_group_gone(self, srv_grp_id):
        """Ensure that the server group is no longer present."""
        server_group = None
        server_groups = self.nova_client.server_groups.list()
        for sg in server_groups:
            if sg.id == srv_grp_id:
                server_group = sg
                break
        if server_group:
            self.fail("Found left-over server group: %s" % server_group)

    def get_instance(self, instance_id, client=None):
        client = client or self.auth_client
        return client.instances.get(instance_id)

    def get_instance_host(self, instance_id=None):
        instance_id = instance_id or self.instance_info.id
        instance = self.get_instance(instance_id)
        host = str(instance._info['ip'][0])
        self.report.log("Found host %s for instance %s." % (host, instance_id))
        return host

    def build_flavor(self, flavor_id=2, volume_size=1):
        return {"flavorRef": flavor_id, "volume": {"size": volume_size}}

    def get_flavor(self, flavor_name):
        flavors = self.auth_client.find_flavors_by_name(flavor_name)
        self.assert_equal(
            1, len(flavors),
            "Unexpected number of flavors with name '%s' found." % flavor_name)
        flavor = flavors[0]
        self.assert_is_not_none(flavor, "Flavor '%s' not found." % flavor_name)

        return flavor

    def get_instance_flavor(self, fault_num=None):
        name_format = 'instance%s%s_flavor_name'
        default = 'm1.tiny'
        fault_str = ''
        eph_str = ''
        if fault_num:
            fault_str = '_fault_%d' % fault_num
        if self.EPHEMERAL_SUPPORT:
            eph_str = '_eph'
            default = 'eph.rd-tiny'

        name = name_format % (fault_str, eph_str)
        flavor_name = CONFIG.values.get(name, default)

        return self.get_flavor(flavor_name)

    def get_flavor_href(self, flavor):
        return self.auth_client.find_flavor_self_href(flavor)

    def copy_dict(self, d, ignored_keys=None):
        return {k: v for k, v in d.items()
                if not ignored_keys or k not in ignored_keys}

    def create_test_helper_on_instance(self, instance_id):
        """Here we add a helper user/database, if any, to a given instance
        via the Trove API.
        These are for internal use by the test framework and should
        not be changed by individual test-cases.
        """
        database_def, user_def, root_def = self.build_helper_defs()
        if database_def:
            self.report.log(
                "Creating a helper database '%s' on instance: %s"
                % (database_def['name'], instance_id))
            self.auth_client.databases.create(instance_id, [database_def])

        if user_def:
            self.report.log(
                "Creating a helper user '%s:%s' on instance: %s"
                % (user_def['name'], user_def['password'], instance_id))
            self.auth_client.users.create(instance_id, [user_def])

        if root_def:
            # Not enabling root on a single instance of the cluster here
            # because we want to test the cluster root enable instead.
            pass

    def build_helper_defs(self):
        """Build helper database and user JSON definitions if credentials
        are defined by the helper.
        """
        database_def = None

        def _get_credentials(creds):
            if creds:
                username = creds.get('name')
                if username:
                    password = creds.get('password', '')
                    return {'name': username, 'password': password,
                            'databases': [{'name': database}]}
            return None

        credentials = self.test_helper.get_helper_credentials()
        if credentials:
            database = credentials.get('database')
            if database:
                database_def = {'name': database}
        credentials_root = self.test_helper.get_helper_credentials_root()

        return (database_def,
                _get_credentials(credentials),
                _get_credentials(credentials_root))


class CheckInstance(AttrCheck):
    """Class to check various attributes of Instance details."""

    def __init__(self, instance):
        super(CheckInstance, self).__init__()
        self.instance = instance
        self.volume_support = TestRunner.VOLUME_SUPPORT
        self.existing_instance = TestRunner.is_using_existing_instance

    def flavor(self):
        if 'flavor' not in self.instance:
            self.fail("'flavor' not found in instance.")
        else:
            allowed_attrs = ['id', 'links']
            self.contains_allowed_attrs(
                self.instance['flavor'], allowed_attrs,
                msg="Flavor")
            self.links(self.instance['flavor']['links'])

    def datastore(self):
        if 'datastore' not in self.instance:
            self.fail("'datastore' not found in instance.")
        else:
            allowed_attrs = ['type', 'version']
            self.contains_allowed_attrs(
                self.instance['datastore'], allowed_attrs,
                msg="datastore")

    def volume_key_exists(self):
        if 'volume' not in self.instance:
            self.fail("'volume' not found in instance.")
            return False
        return True

    def volume(self):
        if not self.volume_support:
            return
        if self.volume_key_exists():
            allowed_attrs = ['size']
            if self.existing_instance:
                allowed_attrs.append('used')
            self.contains_allowed_attrs(
                self.instance['volume'], allowed_attrs,
                msg="Volumes")

    def used_volume(self):
        if not self.volume_support:
            return
        if self.volume_key_exists():
            allowed_attrs = ['size', 'used']
            print(self.instance)
            self.contains_allowed_attrs(
                self.instance['volume'], allowed_attrs,
                msg="Volumes")

    def volume_mgmt(self):
        if not self.volume_support:
            return
        if self.volume_key_exists():
            allowed_attrs = ['description', 'id', 'name', 'size']
            self.contains_allowed_attrs(
                self.instance['volume'], allowed_attrs,
                msg="Volumes")

    def addresses(self):
        allowed_attrs = ['addr', 'version']
        print(self.instance)
        networks = ['usernet']
        for network in networks:
            for address in self.instance['addresses'][network]:
                self.contains_allowed_attrs(
                    address, allowed_attrs,
                    msg="Address")

    def guest_status(self):
        allowed_attrs = ['created_at', 'deleted', 'deleted_at', 'instance_id',
                         'state', 'state_description', 'updated_at']
        self.contains_allowed_attrs(
            self.instance['guest_status'], allowed_attrs,
            msg="Guest status")

    def mgmt_volume(self):
        if not self.volume_support:
            return
        allowed_attrs = ['description', 'id', 'name', 'size']
        self.contains_allowed_attrs(
            self.instance['volume'], allowed_attrs,
            msg="Volume")

    def replica_of(self):
        if 'replica_of' not in self.instance:
            self.fail("'replica_of' not found in instance.")
        else:
            allowed_attrs = ['id', 'links']
            self.contains_allowed_attrs(
                self.instance['replica_of'], allowed_attrs,
                msg="Replica-of links not found")
            self.links(self.instance['replica_of']['links'])

    def slaves(self):
        if 'replicas' not in self.instance:
            self.fail("'replicas' not found in instance.")
        else:
            allowed_attrs = ['id', 'links']
            for slave in self.instance['replicas']:
                self.contains_allowed_attrs(
                    slave, allowed_attrs,
                    msg="Replica links not found")
                self.links(slave['links'])

    def fault(self, is_admin=False):
        if 'fault' not in self.instance:
            self.fail("'fault' not found in instance.")
        else:
            allowed_attrs = ['message', 'created', 'details']
            self.contains_allowed_attrs(
                self.instance['fault'], allowed_attrs,
                msg="Fault")
            if is_admin and not self.instance['fault']['details']:
                self.fail("Missing fault details")
            if not is_admin and self.instance['fault']['details']:
                self.fail("Fault details provided for non-admin")
