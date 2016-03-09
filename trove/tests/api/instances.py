# Copyright 2011 OpenStack Foundation
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

import os
import re
import time
from time import sleep
import unittest
import uuid


from proboscis import after_class
from proboscis.asserts import assert_equal
from proboscis.asserts import assert_false
from proboscis.asserts import assert_is_not_none
from proboscis.asserts import assert_not_equal
from proboscis.asserts import assert_raises
from proboscis.asserts import assert_true
from proboscis.asserts import fail
from proboscis import before_class
from proboscis.decorators import time_out
from proboscis import SkipTest
from proboscis import test
from troveclient.compat import exceptions

from trove.common import exception as rd_exceptions
from trove.common.utils import poll_until
from trove.datastore import models as datastore_models
from trove import tests
from trove.tests.config import CONFIG
from trove.tests.util.check import AttrCheck
from trove.tests.util.check import TypeCheck
from trove.tests.util import create_dbaas_client
from trove.tests.util import create_nova_client
from trove.tests.util import dns_checker
from trove.tests.util import event_simulator
from trove.tests.util import iso_time
from trove.tests.util import test_config
from trove.tests.util.usage import create_usage_verifier
from trove.tests.util.users import Requirements

FAKE = test_config.values['fake_mode']

GROUP = "dbaas.guest"
GROUP_NEUTRON = "dbaas.neutron"
GROUP_START = "dbaas.guest.initialize"
GROUP_START_SIMPLE = "dbaas.guest.initialize.simple"
GROUP_TEST = "dbaas.guest.test"
GROUP_STOP = "dbaas.guest.shutdown"
GROUP_USERS = "dbaas.api.users"
GROUP_ROOT = "dbaas.api.root"
GROUP_GUEST = "dbaas.guest.start.test"
GROUP_DATABASES = "dbaas.api.databases"
GROUP_SECURITY_GROUPS = "dbaas.api.security_groups"
GROUP_CREATE_INSTANCE_FAILURE = "dbaas.api.failures"
GROUP_QUOTAS = "dbaas.quotas"

TIMEOUT_INSTANCE_CREATE = 60 * 32
TIMEOUT_INSTANCE_DELETE = 120


class InstanceTestInfo(object):
    """Stores new instance information used by dependent tests."""

    def __init__(self):
        self.dbaas = None  # The rich client instance used by these tests.
        self.dbaas_admin = None  # The rich client with admin access.
        self.dbaas_flavor = None  # The flavor object of the instance.
        self.dbaas_flavor_href = None  # The flavor of the instance.
        self.dbaas_datastore = None  # The datastore id
        self.dbaas_datastore_version = None  # The datastore version id
        self.dbaas_inactive_datastore_version = None  # The DS inactive id
        self.id = None  # The ID of the instance in the database.
        self.local_id = None
        self.address = None
        self.nics = None  # The dict of type/id for nics used on the intance.
        self.initial_result = None  # The initial result from the create call.
        self.user_ip = None  # The IP address of the instance, given to user.
        self.infra_ip = None  # The infrastructure network IP address.
        self.result = None  # The instance info returned by the API
        self.nova_client = None  # The instance of novaclient.
        self.volume_client = None  # The instance of the volume client.
        self.name = None  # Test name, generated each test run.
        self.pid = None  # The process ID of the instance.
        self.user = None  # The user instance who owns the instance.
        self.admin_user = None  # The admin user for the management interfaces.
        self.volume = None  # The volume the instance will have.
        self.volume_id = None  # Id for the attached vo186lume
        self.storage = None  # The storage device info for the volumes.
        self.databases = None  # The databases created on the instance.
        self.host_info = None  # Host Info before creating instances
        self.user_context = None  # A regular user context
        self.users = None  # The users created on the instance.
        self.consumer = create_usage_verifier()

    def find_default_flavor(self):
        if EPHEMERAL_SUPPORT:
            flavor_name = CONFIG.values.get('instance_eph_flavor_name',
                                            'eph.rd-tiny')
        else:
            flavor_name = CONFIG.values.get('instance_flavor_name', 'm1.tiny')
        flavors = self.dbaas.find_flavors_by_name(flavor_name)
        assert_equal(len(flavors), 1,
                     "Number of flavors with name '%s' "
                     "found was '%d'." % (flavor_name, len(flavors)))
        flavor = flavors[0]
        assert_true(flavor is not None, "Flavor '%s' not found!" % flavor_name)
        flavor_href = self.dbaas.find_flavor_self_href(flavor)
        assert_true(flavor_href is not None,
                    "Flavor href '%s' not found!" % flavor_name)
        return flavor, flavor_href

    def get_address(self):
        result = self.dbaas_admin.mgmt.instances.show(self.id)
        if not hasattr(result, 'hostname'):
            return result.ip[0]
        else:
            return result.server['addresses']

    def get_local_id(self):
        mgmt_instance = self.dbaas_admin.management.show(self.id)
        return mgmt_instance.server["local_id"]

    def get_volume_filesystem_size(self):
        mgmt_instance = self.dbaas_admin.management.show(self.id)
        return mgmt_instance.volume["total"]


# The two variables are used below by tests which depend on an instance
# existing.
instance_info = InstanceTestInfo()
dbaas = None  # Rich client used throughout this test.

dbaas_admin = None  # Same as above, with admin privs.
ROOT_ON_CREATE = CONFIG.get('root_on_create', False)
VOLUME_SUPPORT = CONFIG.get('trove_volume_support', False)
EPHEMERAL_SUPPORT = not VOLUME_SUPPORT and CONFIG.get('device_path',
                                                      '/dev/vdb') is not None
ROOT_PARTITION = not VOLUME_SUPPORT and CONFIG.get('device_path',
                                                   None) is None


# This is like a cheat code which allows the tests to skip creating a new
# instance and use an old one.
def existing_instance():
    return os.environ.get("TESTS_USE_INSTANCE_ID", None)


def do_not_delete_instance():
    return os.environ.get("TESTS_DO_NOT_DELETE_INSTANCE", None) is not None


def create_new_instance():
    return existing_instance() is None


@test(groups=['dbaas.usage', 'dbaas.usage.init'])
def clear_messages_off_queue():
    instance_info.consumer.clear_events()


@test(groups=[GROUP, GROUP_START, GROUP_START_SIMPLE, 'dbaas.setup'],
      depends_on_groups=["services.initialize"])
class InstanceSetup(object):
    """Makes sure the client can hit the ReST service.

    This test also uses the API to find the flavor to use.

    """

    @before_class
    def setUp(self):
        """Sets up the client."""

        reqs = Requirements(is_admin=True)
        instance_info.admin_user = CONFIG.users.find_user(reqs)
        instance_info.dbaas_admin = create_dbaas_client(
            instance_info.admin_user)
        global dbaas_admin
        dbaas_admin = instance_info.dbaas_admin

        # Make sure we create the client as the correct user if we're using
        # a pre-built instance.
        if existing_instance():
            mgmt_inst = dbaas_admin.mgmt.instances.show(existing_instance())
            t_id = mgmt_inst.tenant_id
            instance_info.user = CONFIG.users.find_user_by_tenant_id(t_id)
        else:
            reqs = Requirements(is_admin=False)
            instance_info.user = CONFIG.users.find_user(reqs)

        instance_info.dbaas = create_dbaas_client(instance_info.user)
        global dbaas
        dbaas = instance_info.dbaas

    @test
    def test_find_flavor(self):
        flavor, flavor_href = instance_info.find_default_flavor()
        instance_info.dbaas_flavor = flavor
        instance_info.dbaas_flavor_href = flavor_href

    @test
    def create_instance_name(self):
        id = existing_instance()
        if id is None:
            instance_info.name = "TEST_" + str(uuid.uuid4())
        else:
            instance_info.name = dbaas.instances.get(id).name


@test(depends_on_classes=[InstanceSetup], groups=[GROUP])
def test_delete_instance_not_found():
    """Deletes an instance that does not exist."""
    # Looks for a random UUID that (most probably) does not exist.
    assert_raises(exceptions.NotFound, dbaas.instances.delete,
                  "7016efb6-c02c-403e-9628-f6f57d0920d0")


@test(depends_on_classes=[InstanceSetup],
      groups=[GROUP, GROUP_QUOTAS],
      runs_after_groups=[tests.PRE_INSTANCES])
class CreateInstanceQuotaTest(unittest.TestCase):

    def setUp(self):
        import copy

        self.test_info = copy.deepcopy(instance_info)
        self.test_info.dbaas_datastore = CONFIG.dbaas_datastore

    def tearDown(self):
        quota_dict = {'instances': CONFIG.trove_max_instances_per_tenant,
                      'volumes': CONFIG.trove_max_volumes_per_tenant}
        dbaas_admin.quota.update(self.test_info.user.tenant_id,
                                 quota_dict)

    def test_instance_size_too_big(self):
        if ('trove_max_accepted_volume_size' in CONFIG.values and
                VOLUME_SUPPORT):
            too_big = CONFIG.trove_max_accepted_volume_size

            self.test_info.volume = {'size': too_big + 1}
            self.test_info.name = "way_too_large"
            assert_raises(exceptions.OverLimit,
                          dbaas.instances.create,
                          self.test_info.name,
                          self.test_info.dbaas_flavor_href,
                          self.test_info.volume)

    def test_update_quota_invalid_resource_should_fail(self):
        quota_dict = {'invalid_resource': 100}
        assert_raises(exceptions.NotFound, dbaas_admin.quota.update,
                      self.test_info.user.tenant_id, quota_dict)

    def test_update_quota_volume_should_fail_volume_not_supported(self):
        if VOLUME_SUPPORT:
            raise SkipTest("Volume support needs to be disabled")
        quota_dict = {'volumes': 100}
        assert_raises(exceptions.NotFound, dbaas_admin.quota.update,
                      self.test_info.user.tenant_id, quota_dict)

    def test_create_too_many_instances(self):
        instance_quota = 0
        quota_dict = {'instances': instance_quota}
        new_quotas = dbaas_admin.quota.update(self.test_info.user.tenant_id,
                                              quota_dict)

        verify_quota = dbaas_admin.quota.show(self.test_info.user.tenant_id)

        assert_equal(new_quotas['instances'], quota_dict['instances'])
        assert_equal(0, verify_quota['instances'])
        self.test_info.volume = None

        if VOLUME_SUPPORT:
            assert_equal(CONFIG.trove_max_volumes_per_tenant,
                         verify_quota['volumes'])
            self.test_info.volume = {'size':
                                     CONFIG.get('trove_volume_size', 1)}

        self.test_info.name = "too_many_instances"
        assert_raises(exceptions.OverLimit,
                      dbaas.instances.create,
                      self.test_info.name,
                      self.test_info.dbaas_flavor_href,
                      self.test_info.volume)

        assert_equal(413, dbaas.last_http_code)

    def test_create_instances_total_volume_exceeded(self):
        if not VOLUME_SUPPORT:
            raise SkipTest("Volume support not enabled")
        volume_quota = 3
        quota_dict = {'volumes': volume_quota}
        self.test_info.volume = {'size': volume_quota + 1}
        new_quotas = dbaas_admin.quota.update(self.test_info.user.tenant_id,
                                              quota_dict)
        assert_equal(volume_quota, new_quotas['volumes'])

        self.test_info.name = "too_large_volume"
        assert_raises(exceptions.OverLimit,
                      dbaas.instances.create,
                      self.test_info.name,
                      self.test_info.dbaas_flavor_href,
                      self.test_info.volume)

        assert_equal(413, dbaas.last_http_code)


@test(depends_on_classes=[InstanceSetup],
      groups=[GROUP, GROUP_CREATE_INSTANCE_FAILURE],
      runs_after_groups=[tests.PRE_INSTANCES, GROUP_QUOTAS])
class CreateInstanceFail(object):

    def instance_in_error(self, instance_id):
        def check_if_error():
            instance = dbaas.instances.get(instance_id)
            if instance.status == "ERROR":
                return True
            else:
                # The status should still be BUILD
                assert_equal("BUILD", instance.status)
                return False
        return check_if_error

    def delete_async(self, instance_id):
        dbaas.instances.delete(instance_id)
        while True:
            try:
                dbaas.instances.get(instance_id)
            except exceptions.NotFound:
                return True
            time.sleep(1)

    @test
    @time_out(30)
    def test_create_with_bad_availability_zone(self):
        instance_name = "instance-failure-with-bad-ephemeral"
        if VOLUME_SUPPORT:
            volume = {'size': CONFIG.get('trove_volume_size', 1)}
        else:
            volume = None
        databases = []
        result = dbaas.instances.create(instance_name,
                                        instance_info.dbaas_flavor_href,
                                        volume, databases,
                                        availability_zone="BAD_ZONE")

        poll_until(self.instance_in_error(result.id))
        instance = dbaas.instances.get(result.id)
        assert_equal("ERROR", instance.status)

        self.delete_async(result.id)

    @test
    def test_create_with_bad_nics(self):
        instance_name = "instance-failure-with-bad-nics"
        if VOLUME_SUPPORT:
            volume = {'size': CONFIG.get('trove_volume_size', 1)}
        else:
            volume = None
        databases = []
        bad_nic = [{"port-id": "UNKNOWN", "net-id": "1234",
                    "v4-fixed-ip": "1.2.3.4"}]
        result = dbaas.instances.create(instance_name,
                                        instance_info.dbaas_flavor_href,
                                        volume, databases, nics=bad_nic)

        poll_until(self.instance_in_error(result.id))
        instance = dbaas.instances.get(result.id)
        assert_equal("ERROR", instance.status)

        self.delete_async(result.id)

    def test_create_failure_with_empty_flavor(self):
        instance_name = "instance-failure-with-empty-flavor"
        databases = []
        if VOLUME_SUPPORT:
            volume = {'size': CONFIG.get('trove_volume_size', 1)}
        else:
            volume = None
        assert_raises(exceptions.BadRequest, dbaas.instances.create,
                      instance_name, '',
                      volume, databases)
        assert_equal(400, dbaas.last_http_code)

    @test(enabled=VOLUME_SUPPORT)
    def test_create_failure_with_empty_volume(self):
        instance_name = "instance-failure-with-no-volume-size"
        databases = []
        volume = {}
        assert_raises(exceptions.BadRequest, dbaas.instances.create,
                      instance_name, instance_info.dbaas_flavor_href,
                      volume, databases)
        assert_equal(400, dbaas.last_http_code)

    @test(enabled=VOLUME_SUPPORT)
    def test_create_failure_with_no_volume_size(self):
        instance_name = "instance-failure-with-no-volume-size"
        databases = []
        volume = {'size': None}
        assert_raises(exceptions.BadRequest, dbaas.instances.create,
                      instance_name, instance_info.dbaas_flavor_href,
                      volume, databases)
        assert_equal(400, dbaas.last_http_code)

    @test(enabled=not VOLUME_SUPPORT)
    def test_create_failure_with_volume_size_and_volume_disabled(self):
        instance_name = "instance-failure-volume-size_and_volume_disabled"
        databases = []
        volume = {'size': 2}
        assert_raises(exceptions.HTTPNotImplemented, dbaas.instances.create,
                      instance_name, instance_info.dbaas_flavor_href,
                      volume, databases)
        assert_equal(501, dbaas.last_http_code)

    def test_create_failure_with_volume_size_and_disabled_for_datastore(self):
        instance_name = "instance-failure-volume-size_and_volume_disabled"
        databases = []
        datastore = 'redis'
        assert_equal(CONFIG.get(datastore, 'redis')['volume_support'], False)
        volume = {'size': 2}
        assert_raises(exceptions.HTTPNotImplemented, dbaas.instances.create,
                      instance_name, instance_info.dbaas_flavor_href,
                      volume, databases, datastore=datastore)
        assert_equal(501, dbaas.last_http_code)

    @test(enabled=EPHEMERAL_SUPPORT)
    def test_create_failure_with_no_ephemeral_flavor(self):
        instance_name = "instance-failure-with-no-ephemeral-flavor"
        databases = []
        flavor_name = CONFIG.values.get('instance_flavor_name', 'm1.tiny')
        flavors = dbaas.find_flavors_by_name(flavor_name)
        assert_raises(exceptions.BadRequest, dbaas.instances.create,
                      instance_name, flavors[0].id, None, databases)
        assert_equal(400, dbaas.last_http_code)

    @test
    def test_create_failure_with_no_name(self):
        if VOLUME_SUPPORT:
            volume = {'size': CONFIG.get('trove_volume_size', 1)}
        else:
            volume = None
        instance_name = ""
        databases = []
        assert_raises(exceptions.BadRequest, dbaas.instances.create,
                      instance_name, instance_info.dbaas_flavor_href,
                      volume, databases)
        assert_equal(400, dbaas.last_http_code)

    @test
    def test_create_failure_with_spaces_for_name(self):
        if VOLUME_SUPPORT:
            volume = {'size': CONFIG.get('trove_volume_size', 1)}
        else:
            volume = None
        instance_name = "      "
        databases = []
        assert_raises(exceptions.BadRequest, dbaas.instances.create,
                      instance_name, instance_info.dbaas_flavor_href,
                      volume, databases)
        assert_equal(400, dbaas.last_http_code)

    @test
    def test_mgmt_get_instance_on_create(self):
        if CONFIG.test_mgmt:
            result = dbaas_admin.management.show(instance_info.id)
            allowed_attrs = ['account_id', 'addresses', 'created',
                             'databases', 'flavor', 'guest_status', 'host',
                             'hostname', 'id', 'name', 'datastore',
                             'server_state_description', 'status', 'updated',
                             'users', 'volume', 'root_enabled_at',
                             'root_enabled_by']
            with CheckInstance(result._info) as check:
                check.contains_allowed_attrs(
                    result._info, allowed_attrs,
                    msg="Mgmt get instance")
                check.flavor()
                check.datastore()
                check.guest_status()

    @test
    def test_create_failure_with_datastore_default_notfound(self):
        if not FAKE:
            raise SkipTest("This test only for fake mode.")
        if VOLUME_SUPPORT:
            volume = {'size': CONFIG.get('trove_volume_size', 1)}
        else:
            volume = None
        instance_name = "datastore_default_notfound"
        databases = []
        users = []
        origin_default_datastore = (datastore_models.CONF.
                                    default_datastore)
        datastore_models.CONF.default_datastore = ""
        try:
            assert_raises(exceptions.NotFound,
                          dbaas.instances.create, instance_name,
                          instance_info.dbaas_flavor_href,
                          volume, databases, users)
        except exceptions.BadRequest as e:
            assert_equal(e.message,
                         "Please specify datastore. Default datastore "
                         "cannot be found.")
        datastore_models.CONF.default_datastore = \
            origin_default_datastore

    @test
    def test_create_failure_with_datastore_default_version_notfound(self):
        if VOLUME_SUPPORT:
            volume = {'size': CONFIG.get('trove_volume_size', 1)}
        else:
            volume = None
        instance_name = "datastore_default_version_notfound"
        databases = []
        users = []
        datastore = "Test_Datastore_1"
        try:
            assert_raises(exceptions.NotFound,
                          dbaas.instances.create, instance_name,
                          instance_info.dbaas_flavor_href,
                          volume, databases, users,
                          datastore=datastore)
        except exceptions.BadRequest as e:
            assert_equal(e.message,
                         "Default version for datastore '%s' not found." %
                         datastore)

    @test
    def test_create_failure_with_datastore_notfound(self):
        if VOLUME_SUPPORT:
            volume = {'size': CONFIG.get('trove_volume_size', 1)}
        else:
            volume = None
        instance_name = "datastore_notfound"
        databases = []
        users = []
        datastore = "nonexistent"
        try:
            assert_raises(exceptions.NotFound,
                          dbaas.instances.create, instance_name,
                          instance_info.dbaas_flavor_href,
                          volume, databases, users,
                          datastore=datastore)
        except exceptions.BadRequest as e:
            assert_equal(e.message,
                         "Datastore '%s' cannot be found." %
                         datastore)

    @test
    def test_create_failure_with_datastore_version_notfound(self):
        if VOLUME_SUPPORT:
            volume = {'size': CONFIG.get('trove_volume_size', 1)}
        else:
            volume = None
        instance_name = "datastore_version_notfound"
        databases = []
        users = []
        datastore = CONFIG.dbaas_datastore
        datastore_version = "nonexistent"
        try:
            assert_raises(exceptions.NotFound,
                          dbaas.instances.create, instance_name,
                          instance_info.dbaas_flavor_href,
                          volume, databases, users,
                          datastore=datastore,
                          datastore_version=datastore_version)
        except exceptions.BadRequest as e:
            assert_equal(e.message,
                         "Datastore version '%s' cannot be found." %
                         datastore_version)

    @test
    def test_create_failure_with_datastore_version_inactive(self):
        if VOLUME_SUPPORT:
            volume = {'size': CONFIG.get('trove_volume_size', 1)}
        else:
            volume = None
        instance_name = "datastore_version_inactive"
        databases = []
        users = []
        datastore = CONFIG.dbaas_datastore
        datastore_version = CONFIG.dbaas_inactive_datastore_version
        try:
            assert_raises(exceptions.NotFound,
                          dbaas.instances.create, instance_name,
                          instance_info.dbaas_flavor_href,
                          volume, databases, users,
                          datastore=datastore,
                          datastore_version=datastore_version)
        except exceptions.BadRequest as e:
            assert_equal(e.message,
                         "Datastore version '%s' is not active." %
                         datastore_version)


def assert_unprocessable(func, *args):
    try:
        func(*args)
        # If the exception didn't get raised, but the instance is still in
        # the BUILDING state, that's a bug.
        result = dbaas.instances.get(instance_info.id)
        if result.status == "BUILD":
            fail("When an instance is being built, this function should "
                 "always raise UnprocessableEntity.")
    except exceptions.UnprocessableEntity:
        assert_equal(422, dbaas.last_http_code)
        pass  # Good

    @test
    def test_deep_list_security_group_with_rules(self):
        securityGroupList = dbaas.security_groups.list()
        assert_is_not_none(securityGroupList)
        securityGroup = [x for x in securityGroupList
                         if x.name in self.secGroupName]
        assert_is_not_none(securityGroup[0])
        assert_not_equal(len(securityGroup[0].rules), 0)


@test(depends_on_classes=[InstanceSetup],
      run_after_class=[CreateInstanceFail],
      groups=[GROUP, GROUP_START, GROUP_START_SIMPLE, tests.INSTANCES],
      runs_after_groups=[tests.PRE_INSTANCES, GROUP_QUOTAS])
class CreateInstance(object):

    """Test to create a Database Instance

    If the call returns without raising an exception this test passes.

    """

    @test
    def test_create(self):
        databases = []
        databases.append({"name": "firstdb", "character_set": "latin2",
                          "collate": "latin2_general_ci"})
        databases.append({"name": "db2"})
        instance_info.databases = databases
        users = []
        users.append({"name": "lite", "password": "litepass",
                      "databases": [{"name": "firstdb"}]})
        instance_info.users = users
        instance_info.dbaas_datastore = CONFIG.dbaas_datastore
        instance_info.dbaas_datastore_version = CONFIG.dbaas_datastore_version
        if VOLUME_SUPPORT:
            instance_info.volume = {'size': CONFIG.get('trove_volume_size', 1)}
        else:
            instance_info.volume = None

        shared_network = CONFIG.get('shared_network', None)
        if shared_network:
            instance_info.nics = [{'net-id': shared_network}]

        if create_new_instance():
            instance_info.initial_result = dbaas.instances.create(
                instance_info.name,
                instance_info.dbaas_flavor_href,
                instance_info.volume,
                databases,
                users,
                nics=instance_info.nics,
                availability_zone="nova",
                datastore=instance_info.dbaas_datastore,
                datastore_version=instance_info.dbaas_datastore_version)
            assert_equal(200, dbaas.last_http_code)
        else:
            id = existing_instance()
            instance_info.initial_result = dbaas.instances.get(id)

        result = instance_info.initial_result
        instance_info.id = result.id
        instance_info.dbaas_datastore_version = result.datastore['version']

        report = CONFIG.get_report()
        report.log("Instance UUID = %s" % instance_info.id)
        if create_new_instance():
            assert_equal("BUILD", instance_info.initial_result.status)

        else:
            report.log("Test was invoked with TESTS_USE_INSTANCE_ID=%s, so no "
                       "instance was actually created." % id)

        # Check these attrs only are returned in create response
        allowed_attrs = ['created', 'flavor', 'addresses', 'id', 'links',
                         'name', 'status', 'updated', 'datastore']
        if ROOT_ON_CREATE:
            allowed_attrs.append('password')
        if VOLUME_SUPPORT:
            allowed_attrs.append('volume')
        if CONFIG.trove_dns_support:
            allowed_attrs.append('hostname')

        with CheckInstance(result._info) as check:
            if create_new_instance():
                check.contains_allowed_attrs(
                    result._info, allowed_attrs,
                    msg="Create response")
            # Don't CheckInstance if the instance already exists.
            check.flavor()
            check.datastore()
            check.links(result._info['links'])
            if VOLUME_SUPPORT:
                check.volume()


@test(depends_on_classes=[InstanceSetup],
      groups=[GROUP, tests.INSTANCES],
      runs_after_groups=[tests.PRE_INSTANCES])
class CreateInstanceFlavors(object):

    def _result_is_active(self):
        instance = dbaas.instances.get(self.result.id)
        if instance.status == "ACTIVE":
            return True
        else:
            # If its not ACTIVE, anything but BUILD must be
            # an error.
            assert_equal("BUILD", instance.status)
            if instance_info.volume is not None:
                assert_equal(instance.volume.get('used', None), None)
            return False

    def _delete_async(self, instance_id):
        dbaas.instances.delete(instance_id)
        while True:
            try:
                dbaas.instances.get(instance_id)
            except exceptions.NotFound:
                return True
            time.sleep(1)

    def _create_with_flavor(self, flavor_id):
        if not FAKE:
            raise SkipTest("This test only for fake mode.")
        instance_name = "instance-with-flavor-%s" % flavor_id
        databases = []
        if VOLUME_SUPPORT:
            volume = {'size': CONFIG.get('trove_volume_size', 1)}
        else:
            volume = None
        self.result = dbaas.instances.create(instance_name, flavor_id, volume,
                                             databases)
        poll_until(self._result_is_active)
        self._delete_async(self.result.id)

    @test
    def test_create_with_int_flavor(self):
        self._create_with_flavor(1)

    @test
    def test_create_with_str_flavor(self):
        self._create_with_flavor('custom')


@test(depends_on_classes=[InstanceSetup], groups=[GROUP_NEUTRON])
class CreateInstanceWithNeutron(unittest.TestCase):

    @time_out(TIMEOUT_INSTANCE_CREATE)
    def setUp(self):
        if not CONFIG.values.get('neutron_enabled'):
            raise SkipTest("neutron is not enabled, skipping")

        user = test_config.users.find_user(
            Requirements(is_admin=False, services=["nova", "trove"]))
        self.nova_client = create_nova_client(user)
        self.dbaas_client = create_dbaas_client(user)

        self.result = None
        self.instance_name = ("TEST_INSTANCE_CREATION_WITH_NICS"
                              + str(uuid.uuid4()))
        databases = []
        self.default_cidr = CONFIG.values.get('shared_network_subnet', None)
        if VOLUME_SUPPORT:
            volume = {'size': CONFIG.get('trove_volume_size', 1)}
        else:
            volume = None

        self.result = self.dbaas_client.instances.create(
            self.instance_name,
            instance_info.dbaas_flavor_href,
            volume, databases)
        self.instance_id = self.result.id

        def verify_instance_is_active():
            result = self.dbaas_client.instances.get(self.instance_id)
            if result.status == "ACTIVE":
                return True
            else:
                assert_equal("BUILD", result.status)
                return False

        poll_until(verify_instance_is_active)

    def tearDown(self):
        if self.result.id is not None:
            self.dbaas_client.instances.delete(self.result.id)
            while True:
                try:
                    self.dbaas_client.instances.get(self.result.id)
                except exceptions.NotFound:
                    return True
                time.sleep(1)

    def check_ip_within_network(self, ip, network):
        octet_list = str(ip).split(".")

        octets, mask = str(network).split("/")
        octet_list_ = octets.split(".")

        for i in range(int(mask) / 8):
            if octet_list[i] != octet_list_[i]:
                return False

        return True

    def test_ip_within_cidr(self):
        nova_instance = None
        for server in self.nova_client.servers.list():
            if str(server.name) == self.instance_name:
                nova_instance = server
                break

        if nova_instance is None:
            fail("instance created with neutron enabled is not found in nova")

        for address in nova_instance.addresses['private']:
            ip = address['addr']
            assert_true(self.check_ip_within_network(ip, self.default_cidr))

        # black list filtered ip not visible via troveclient
        trove_instance = self.dbaas_client.instances.get(self.result.id)

        for ip in trove_instance.ip:
            if str(ip).startswith('10.'):
                assert_true(self.check_ip_within_network(ip, "10.0.0.0/24"))
                assert_false(self.check_ip_within_network(ip, "10.0.1.0/24"))


@test(depends_on_classes=[CreateInstance],
      groups=[GROUP,
              GROUP_START,
              GROUP_START_SIMPLE,
              'dbaas.mgmt.hosts_post_install'],
      enabled=create_new_instance())
class AfterInstanceCreation(unittest.TestCase):

    # instance calls
    def test_instance_delete_right_after_create(self):
        assert_unprocessable(dbaas.instances.delete, instance_info.id)

    # root calls
    def test_root_create_root_user_after_create(self):
        assert_unprocessable(dbaas.root.create, instance_info.id)

    def test_root_is_root_enabled_after_create(self):
        assert_unprocessable(dbaas.root.is_root_enabled, instance_info.id)

    # database calls
    def test_database_index_after_create(self):
        assert_unprocessable(dbaas.databases.list, instance_info.id)

    def test_database_delete_after_create(self):
        assert_unprocessable(dbaas.databases.delete, instance_info.id,
                             "testdb")

    def test_database_create_after_create(self):
        assert_unprocessable(dbaas.databases.create, instance_info.id,
                             instance_info.databases)

    # user calls
    def test_users_index_after_create(self):
        assert_unprocessable(dbaas.users.list, instance_info.id)

    def test_users_delete_after_create(self):
        assert_unprocessable(dbaas.users.delete, instance_info.id,
                             "testuser")

    def test_users_create_after_create(self):
        users = list()
        users.append({"name": "testuser", "password": "password",
                      "databases": [{"name": "testdb"}]})
        assert_unprocessable(dbaas.users.create, instance_info.id, users)

    def test_resize_instance_after_create(self):
        assert_unprocessable(dbaas.instances.resize_instance,
                             instance_info.id, 8)

    def test_resize_volume_after_create(self):
        assert_unprocessable(dbaas.instances.resize_volume,
                             instance_info.id, 2)


@test(depends_on_classes=[CreateInstance],
      runs_after=[AfterInstanceCreation],
      groups=[GROUP, GROUP_START, GROUP_START_SIMPLE],
      enabled=create_new_instance())
class WaitForGuestInstallationToFinish(object):
    """
        Wait until the Guest is finished installing.  It takes quite a while...
    """

    @test
    @time_out(TIMEOUT_INSTANCE_CREATE)
    def test_instance_created(self):
        # This version just checks the REST API status.
        def result_is_active():
            instance = dbaas.instances.get(instance_info.id)
            if instance.status == "ACTIVE":
                return True
            else:
                # If its not ACTIVE, anything but BUILD must be
                # an error.
                assert_equal("BUILD", instance.status)
                if instance_info.volume is not None:
                    assert_equal(instance.volume.get('used', None), None)
                return False

        poll_until(result_is_active)
        dbaas.instances.get(instance_info.id)

        report = CONFIG.get_report()
        report.log("Created an instance, ID = %s." % instance_info.id)
        report.log("TIP:")
        report.log("Rerun the tests with TESTS_USE_INSTANCE_ID=%s "
                   "to skip ahead to this point." % instance_info.id)
        report.log("Add TESTS_DO_NOT_DELETE_INSTANCE=True to avoid deleting "
                   "the instance at the end of the tests.")


@test(depends_on_classes=[WaitForGuestInstallationToFinish],
      groups=[GROUP, GROUP_SECURITY_GROUPS])
class SecurityGroupsTest(object):

    @before_class
    def setUp(self):
        self.testSecurityGroup = dbaas.security_groups.get(
            instance_info.id)
        self.secGroupName = "SecGroup_%s" % instance_info.id
        self.secGroupDescription = "Security Group for %s" % instance_info.id

    @test
    def test_created_security_group(self):
        assert_is_not_none(self.testSecurityGroup)
        with TypeCheck('SecurityGroup', self.testSecurityGroup) as secGrp:
            secGrp.has_field('id', basestring)
            secGrp.has_field('name', basestring)
            secGrp.has_field('description', basestring)
            secGrp.has_field('created', basestring)
            secGrp.has_field('updated', basestring)
        assert_equal(self.testSecurityGroup.name, self.secGroupName)
        assert_equal(self.testSecurityGroup.description,
                     self.secGroupDescription)
        assert_equal(self.testSecurityGroup.created,
                     self.testSecurityGroup.updated)

    @test
    def test_list_security_group(self):
        securityGroupList = dbaas.security_groups.list()
        assert_is_not_none(securityGroupList)
        securityGroup = [x for x in securityGroupList
                         if x.name in self.secGroupName]
        assert_is_not_none(securityGroup)

    @test
    def test_get_security_group(self):
        securityGroup = dbaas.security_groups.get(self.testSecurityGroup.id)
        assert_is_not_none(securityGroup)
        assert_equal(securityGroup.name, self.secGroupName)
        assert_equal(securityGroup.description, self.secGroupDescription)
        assert_equal(securityGroup.instance_id, instance_info.id)


@test(depends_on_classes=[SecurityGroupsTest],
      groups=[GROUP, GROUP_SECURITY_GROUPS])
class SecurityGroupsRulesTest(object):

    # Security group already have default rule
    # that is why 'delete'-test is not needed anymore

    @before_class
    def setUp(self):
        self.testSecurityGroup = dbaas.security_groups.get(
            instance_info.id)
        self.secGroupName = "SecGroup_%s" % instance_info.id
        self.secGroupDescription = "Security Group for %s" % instance_info.id
        self.orig_allowable_empty_sleeps = (event_simulator.
                                            allowable_empty_sleeps)
        event_simulator.allowable_empty_sleeps = 2
        self.test_rule_id = None

    @after_class
    def tearDown(self):
        (event_simulator.
         allowable_empty_sleeps) = self.orig_allowable_empty_sleeps

    @test
    def test_create_security_group_rule(self):
        # Need to sleep to verify created/updated timestamps
        time.sleep(1)
        cidr = "1.2.3.4/16"
        self.testSecurityGroupRules = (
            dbaas.security_group_rules.create(
                group_id=self.testSecurityGroup.id,
                cidr=cidr))
        assert_not_equal(len(self.testSecurityGroupRules), 0)
        assert_is_not_none(self.testSecurityGroupRules)
        for rule in self.testSecurityGroupRules:
            assert_is_not_none(rule)
            assert_equal(rule['security_group_id'],
                         self.testSecurityGroup.id)
            assert_is_not_none(rule['id'])
            assert_equal(rule['cidr'], cidr)
            assert_equal(rule['from_port'], 3306)
            assert_equal(rule['to_port'], 3306)
            assert_is_not_none(rule['created'])
            self.test_rule_id = rule['id']

        if not CONFIG.fake_mode:
            group = dbaas.security_groups.get(
                self.testSecurityGroup.id)
            assert_not_equal(self.testSecurityGroup.created,
                             group.updated)
            assert_not_equal(self.testSecurityGroup.updated,
                             group.updated)

    @test(depends_on=[test_create_security_group_rule])
    def test_delete_security_group_rule(self):
        # Need to sleep to verify created/updated timestamps
        time.sleep(1)
        group_before = dbaas.security_groups.get(
            self.testSecurityGroup.id)
        dbaas.security_group_rules.delete(self.test_rule_id)
        assert_equal(204, dbaas.last_http_code)

        if not CONFIG.fake_mode:
            group = dbaas.security_groups.get(
                self.testSecurityGroup.id)
            assert_not_equal(group_before.created,
                             group.updated)
            assert_not_equal(group_before.updated,
                             group.updated)
            assert_not_equal(self.testSecurityGroup,
                             group.updated)


@test(depends_on_classes=[WaitForGuestInstallationToFinish],
      groups=[GROUP, GROUP_START], enabled=create_new_instance())
class TestGuestProcess(object):
    """
        Test that the guest process is started with all the right parameters
    """

    @test
    def check_hwinfo_before_tests(self):
        if CONFIG.test_mgmt:
            hwinfo = dbaas_admin.hwinfo.get(instance_info.id)
            print("hwinfo : %r" % hwinfo._info)
            allowed_attrs = ['hwinfo']
            CheckInstance(None).contains_allowed_attrs(
                hwinfo._info, allowed_attrs,
                msg="Hardware information")
            # TODO(pdmars): instead of just checking that these are int's, get
            # the instance flavor and verify that the values are correct for
            # the flavor
            assert_true(isinstance(hwinfo.hwinfo['mem_total'], int))
            assert_true(isinstance(hwinfo.hwinfo['num_cpus'], int))

    @test
    def grab_diagnostics_before_tests(self):
        if CONFIG.test_mgmt:
            diagnostics = dbaas_admin.diagnostics.get(instance_info.id)
            diagnostic_tests_helper(diagnostics)


@test(depends_on_classes=[WaitForGuestInstallationToFinish],
      groups=[GROUP, GROUP_TEST, "dbaas.dns"])
class DnsTests(object):

    @test
    def test_dns_entries_are_found(self):
        """Talk to DNS system to ensure entries were created."""
        print("Instance name=%s" % instance_info.name)
        client = instance_info.dbaas_admin
        mgmt_instance = client.mgmt.instances.show(instance_info.id)
        dns_checker(mgmt_instance)


@test(depends_on_classes=[WaitForGuestInstallationToFinish],
      groups=[GROUP, GROUP_TEST, GROUP_GUEST])
class TestAfterInstanceCreatedGuestData(object):
    """
    Test the optional parameters (databases and users) passed in to create
    instance call were created.
    """

    @test
    def test_databases(self):
        databases = dbaas.databases.list(instance_info.id)
        dbs = [database.name for database in databases]
        for db in instance_info.databases:
            assert_true(db["name"] in dbs)

    @test
    def test_users(self):
        users = dbaas.users.list(instance_info.id)
        usernames = [user.name for user in users]
        for user in instance_info.users:
            assert_true(user["name"] in usernames)


@test(depends_on_classes=[WaitForGuestInstallationToFinish],
      groups=[GROUP, GROUP_START, GROUP_START_SIMPLE, "dbaas.listing"])
class TestInstanceListing(object):
    """Test the listing of the instance information."""

    @before_class
    def setUp(self):
        reqs = Requirements(is_admin=False)
        self.other_user = CONFIG.users.find_user(
            reqs,
            black_list=[instance_info.user.auth_user])
        self.other_client = create_dbaas_client(self.other_user)

    @test
    def test_index_list(self):
        allowed_attrs = ['id', 'links', 'name', 'status', 'flavor',
                         'datastore', 'ip', 'hostname', 'replica_of']
        if VOLUME_SUPPORT:
            allowed_attrs.append('volume')
        instances = dbaas.instances.list()
        assert_equal(200, dbaas.last_http_code)
        for instance in instances:
            instance_dict = instance._info
            with CheckInstance(instance_dict) as check:
                print("testing instance_dict=%s" % instance_dict)
                check.contains_allowed_attrs(
                    instance_dict, allowed_attrs,
                    msg="Instance Index")
                check.links(instance_dict['links'])
                check.flavor()
                check.datastore()
                check.volume()

    @test
    def test_get_instance(self):
        allowed_attrs = ['created', 'databases', 'flavor', 'hostname', 'id',
                         'links', 'name', 'status', 'updated', 'ip',
                         'datastore']
        if VOLUME_SUPPORT:
            allowed_attrs.append('volume')
        else:
            allowed_attrs.append('local_storage')
        instance = dbaas.instances.get(instance_info.id)
        assert_equal(200, dbaas.last_http_code)
        instance_dict = instance._info
        print("instance_dict=%s" % instance_dict)
        with CheckInstance(instance_dict) as check:
            check.contains_allowed_attrs(
                instance_dict, allowed_attrs,
                msg="Get Instance")
            check.flavor()
            check.datastore()
            check.links(instance_dict['links'])
            check.used_volume()

    @test
    def test_get_instance_status(self):
        result = dbaas.instances.get(instance_info.id)
        assert_equal(200, dbaas.last_http_code)
        assert_equal("ACTIVE", result.status)

    @test
    def test_get_legacy_status(self):
        result = dbaas.instances.get(instance_info.id)
        assert_equal(200, dbaas.last_http_code)
        assert_true(result is not None)

    @test
    def test_get_legacy_status_notfound(self):
        assert_raises(exceptions.NotFound, dbaas.instances.get, -2)

    @test(enabled=VOLUME_SUPPORT)
    def test_volume_found(self):
        instance = dbaas.instances.get(instance_info.id)
        if create_new_instance():
            assert_equal(instance_info.volume['size'], instance.volume['size'])
        else:
            # FIXME(peterstac): Sometimes this returns as an int - is that ok?
            assert_true(type(instance_info.volume['size']) in [int, float])
        if create_new_instance():
            # FIXME(pmalik): Keeps failing because 'used' > 'size'.
            # It seems like the reported 'used' space is from the root volume
            # instead of the attached Trove volume.
            # assert_true(0.0 < instance.volume['used'] <
            #            instance.volume['size'])
            pass

    @test(enabled=EPHEMERAL_SUPPORT)
    def test_ephemeral_mount(self):
        instance = dbaas.instances.get(instance_info.id)
        assert_true(isinstance(instance.local_storage['used'], float))

    @test(enabled=ROOT_PARTITION)
    def test_root_partition(self):
        instance = dbaas.instances.get(instance_info.id)
        assert_true(isinstance(instance.local_storage['used'], float))

    @test(enabled=do_not_delete_instance())
    def test_instance_not_shown_to_other_user(self):
        daffy_ids = [instance.id for instance in
                     self.other_client.instances.list()]
        assert_equal(200, self.other_client.last_http_code)
        admin_ids = [instance.id for instance in dbaas.instances.list()]
        assert_equal(200, dbaas.last_http_code)
        assert_equal(len(daffy_ids), 0)
        assert_not_equal(sorted(admin_ids), sorted(daffy_ids))
        assert_raises(exceptions.NotFound,
                      self.other_client.instances.get, instance_info.id)
        for id in admin_ids:
            assert_equal(daffy_ids.count(id), 0)

    @test(enabled=do_not_delete_instance())
    def test_instance_not_deleted_by_other_user(self):
        assert_raises(exceptions.NotFound,
                      self.other_client.instances.get, instance_info.id)
        assert_raises(exceptions.NotFound,
                      self.other_client.instances.delete, instance_info.id)

    @test(enabled=CONFIG.test_mgmt)
    def test_mgmt_get_instance_after_started(self):
        result = dbaas_admin.management.show(instance_info.id)
        allowed_attrs = ['account_id', 'addresses', 'created', 'databases',
                         'flavor', 'guest_status', 'host', 'hostname', 'id',
                         'name', 'root_enabled_at', 'root_enabled_by',
                         'server_state_description', 'status', 'datastore',
                         'updated', 'users', 'volume']
        with CheckInstance(result._info) as check:
            check.contains_allowed_attrs(
                result._info, allowed_attrs,
                msg="Mgmt get instance")
            check.flavor()
            check.datastore()
            check.guest_status()
            check.addresses()
            check.volume_mgmt()


@test(depends_on_classes=[WaitForGuestInstallationToFinish],
      groups=[GROUP, GROUP_START, GROUP_START_SIMPLE, "dbaas.update"])
class TestInstanceUpdate(object):
    """Test the updation of the instance information."""

    @before_class
    def setUp(self):
        reqs = Requirements(is_admin=False)
        self.other_user = CONFIG.users.find_user(
            reqs,
            black_list=[instance_info.user.auth_user])
        self.other_client = create_dbaas_client(self.other_user)

    @test
    def test_update_name(self):
        new_name = 'new-name'
        result = dbaas.instances.edit(instance_info.id, name=new_name)
        assert_equal(202, dbaas.last_http_code)
        result = dbaas.instances.get(instance_info.id)
        assert_equal(200, dbaas.last_http_code)
        assert_equal(new_name, result.name)
        # Restore instance name because other tests depend on it
        dbaas.instances.edit(instance_info.id, name=instance_info.name)
        assert_equal(202, dbaas.last_http_code)

    @test
    def test_update_name_to_invalid_instance(self):
        # test assigning to an instance that does not exist
        invalid_id = "invalid-inst-id"
        assert_raises(exceptions.NotFound, instance_info.dbaas.instances.edit,
                      invalid_id, name='name')
        assert_equal(404, instance_info.dbaas.last_http_code)


@test(depends_on_classes=[WaitForGuestInstallationToFinish],
      groups=[GROUP, 'dbaas.usage'])
class TestCreateNotification(object):
    """
    Test that the create notification has been sent correctly.
    """

    @test
    def test_create_notification(self):
        expected = {
            'instance_size': instance_info.dbaas_flavor.ram,
            'tenant_id': instance_info.user.tenant_id,
            'instance_id': instance_info.id,
            'instance_name': instance_info.name,
            'created_at': iso_time(instance_info.initial_result.created),
            'launched_at': iso_time(instance_info.initial_result.created),
            'region': 'LOCAL_DEV',
            'availability_zone': 'nova',
        }
        instance_info.consumer.check_message(instance_info.id,
                                             'trove.instance.create',
                                             **expected)


@test(depends_on_groups=['dbaas.api.instances.actions'],
      groups=[GROUP, tests.INSTANCES, "dbaas.diagnostics"])
class CheckDiagnosticsAfterTests(object):
    """Check the diagnostics after running api commands on an instance."""
    @test
    def test_check_diagnostics_on_instance_after_tests(self):
        diagnostics = dbaas_admin.diagnostics.get(instance_info.id)
        assert_equal(200, dbaas.last_http_code)
        diagnostic_tests_helper(diagnostics)
        msg = "Fat Pete has emerged. size (%s > 30MB)" % diagnostics.vmPeak
        assert_true(diagnostics.vmPeak < (30 * 1024), msg)


@test(depends_on=[WaitForGuestInstallationToFinish],
      depends_on_groups=[GROUP_USERS, GROUP_DATABASES, GROUP_ROOT],
      groups=[GROUP, GROUP_STOP],
      runs_after_groups=[GROUP_START,
                         GROUP_START_SIMPLE, GROUP_TEST, tests.INSTANCES])
class DeleteInstance(object):
    """Delete the created instance."""

    @time_out(3 * 60)
    @test
    def test_delete(self):
        if do_not_delete_instance():
            CONFIG.get_report().log("TESTS_DO_NOT_DELETE_INSTANCE=True was "
                                    "specified, skipping delete...")
            raise SkipTest("TESTS_DO_NOT_DELETE_INSTANCE was specified.")
        global dbaas
        if not hasattr(instance_info, "initial_result"):
            raise SkipTest("Instance was never created, skipping test...")
        # Update the report so the logs inside the instance will be saved.
        CONFIG.get_report().update()
        dbaas.instances.delete(instance_info.id)

        attempts = 0
        try:
            time.sleep(1)
            result = True
            while result is not None:
                attempts += 1
                result = dbaas.instances.get(instance_info.id)
                assert_equal(200, dbaas.last_http_code)
                assert_equal("SHUTDOWN", result.status)
                time.sleep(1)
        except exceptions.NotFound:
            pass
        except Exception as ex:
            fail("A failure occurred when trying to GET instance %s for the %d"
                 " time: %s" % (str(instance_info.id), attempts, str(ex)))

    @time_out(30)
    @test(enabled=VOLUME_SUPPORT,
          depends_on=[test_delete])
    def test_volume_is_deleted(self):
        try:
            while True:
                instance = dbaas.instances.get(instance_info.id)
                assert_equal(instance.volume['status'], "available")
                time.sleep(1)
        except exceptions.NotFound:
            pass
        except Exception as ex:
            fail("Failure: %s" % str(ex))

    # TODO(tim-simpson): make sure that the actual instance, volume,
    # guest status, and DNS entries are deleted.


@test(depends_on=[WaitForGuestInstallationToFinish],
      runs_after=[DeleteInstance],
      groups=[GROUP, GROUP_STOP, 'dbaas.usage'])
class AfterDeleteChecks(object):

    @test
    def test_instance_delete_event_sent(self):
        deleted_at = None
        mgmt_details = dbaas_admin.management.index(deleted=True)
        for instance in mgmt_details:
            if instance.id == instance_info.id:
                deleted_at = instance.deleted_at
        expected = {
            'instance_size': instance_info.dbaas_flavor.ram,
            'tenant_id': instance_info.user.tenant_id,
            'instance_id': instance_info.id,
            'instance_name': instance_info.name,
            'created_at': iso_time(instance_info.initial_result.created),
            'launched_at': iso_time(instance_info.initial_result.created),
            'deleted_at': iso_time(deleted_at),
        }
        instance_info.consumer.check_message(instance_info.id,
                                             'trove.instance.delete',
                                             **expected)

    @test
    def test_instance_status_deleted_in_db(self):
        mgmt_details = dbaas_admin.management.index(deleted=True)
        for instance in mgmt_details:
            if instance.id == instance_info.id:
                assert_equal(instance.service_status, 'DELETED')
                break
        else:
            fail("Could not find instance %s" % instance_info.id)


@test(depends_on_classes=[CreateInstance,
                          WaitForGuestInstallationToFinish],
      groups=[GROUP, GROUP_START, GROUP_START_SIMPLE],
      enabled=CONFIG.test_mgmt)
class VerifyInstanceMgmtInfo(object):

    @before_class
    def set_up(self):
        self.mgmt_details = dbaas_admin.management.show(instance_info.id)

    def _assert_key(self, k, expected):
        v = getattr(self.mgmt_details, k)
        err = "Key %r does not match expected value of %r (was %r)." \
              % (k, expected, v)
        assert_equal(str(v), str(expected), err)

    @test
    def test_id_matches(self):
        self._assert_key('id', instance_info.id)

    @test
    def test_bogus_instance_mgmt_data(self):
        # Make sure that a management call to a bogus API 500s.
        # The client reshapes the exception into just an OpenStackException.
        assert_raises(exceptions.NotFound,
                      dbaas_admin.management.show, -1)

    @test
    def test_mgmt_ips_associated(self):
        # Test that the management index properly associates an instances with
        # ONLY its IPs.
        mgmt_index = dbaas_admin.management.index()
        # Every instances has exactly one address.
        for instance in mgmt_index:
            assert_equal(1, len(instance.ips))

    @test
    def test_mgmt_data(self):
        # Test that the management API returns all the values we expect it to.
        info = instance_info
        ir = info.initial_result
        cid = ir.id
        expected = {
            'id': cid,
            'name': ir.name,
            'account_id': info.user.auth_user,
            # TODO(hub-cap): fix this since its a flavor object now
            # 'flavorRef': info.dbaas_flavor_href,
            'databases': [
                {
                    'name': 'db2',
                    'character_set': 'utf8',
                    'collate': 'utf8_general_ci',
                },
                {
                    'name': 'firstdb',
                    'character_set': 'latin2',
                    'collate': 'latin2_general_ci',
                }
            ],
        }

        expected_entry = info.expected_dns_entry()
        if expected_entry:
            expected['hostname'] = expected_entry.name

        assert_true(self.mgmt_details is not None)
        for (k, v) in expected.items():
            msg = "Attr %r is missing." % k
            assert_true(hasattr(self.mgmt_details, k), msg)
            msg = ("Attr %r expected to be %r but was %r." %
                   (k, v, getattr(self.mgmt_details, k)))
            assert_equal(getattr(self.mgmt_details, k), v, msg)
        print(self.mgmt_details.users)
        for user in self.mgmt_details.users:
            assert_true('name' in user, "'name' not in users element.")


class CheckInstance(AttrCheck):
    """Class to check various attributes of Instance details."""

    def __init__(self, instance):
        super(CheckInstance, self).__init__()
        self.instance = instance

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
        if not VOLUME_SUPPORT:
            return
        if self.volume_key_exists():
            allowed_attrs = ['size']
            if not create_new_instance():
                allowed_attrs.append('used')
            self.contains_allowed_attrs(
                self.instance['volume'], allowed_attrs,
                msg="Volumes")

    def used_volume(self):
        if not VOLUME_SUPPORT:
            return
        if self.volume_key_exists():
            allowed_attrs = ['size', 'used']
            print(self.instance)
            self.contains_allowed_attrs(
                self.instance['volume'], allowed_attrs,
                msg="Volumes")

    def volume_mgmt(self):
        if not VOLUME_SUPPORT:
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
        if not VOLUME_SUPPORT:
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


@test(groups=[GROUP])
class BadInstanceStatusBug():

    @before_class()
    def setUp(self):
        self.instances = []
        reqs = Requirements(is_admin=True)
        self.user = CONFIG.users.find_user(
            reqs, black_list=[])
        self.client = create_dbaas_client(self.user)
        self.mgmt = self.client.management

    @test
    def test_instance_status_after_double_migrate(self):
        """
        This test is to verify that instance status returned is more
        informative than 'Status is {}'.  There are several ways to
        replicate this error.  A double migration is just one of them but
        since this is a known way to recreate that error we will use it
        here to be sure that the error is fixed.  The actual code lives
        in trove/instance/models.py in _validate_can_perform_action()
        """
        # TODO(imsplitbit): test other instances where this issue could be
        # replicated.  Resizing a resized instance awaiting confirmation
        # can be used as another case.  This all boils back to the same
        # piece of code so I'm not sure if it's relevant or not but could
        # be done.
        size = None
        if VOLUME_SUPPORT:
            size = {'size': 5}

        result = self.client.instances.create('testbox',
                                              instance_info.dbaas_flavor_href,
                                              size)
        id = result.id
        self.instances.append(id)

        def verify_instance_is_active():
            result = self.client.instances.get(id)
            print(result.status)
            return result.status == 'ACTIVE'

        def attempt_migrate():
            print('attempting migration')
            try:
                self.mgmt.migrate(id)
            except exceptions.UnprocessableEntity:
                return False
            return True

        # Timing necessary to make the error occur
        poll_until(verify_instance_is_active, time_out=120, sleep_time=1)

        try:
            poll_until(attempt_migrate, time_out=10, sleep_time=1)
        except rd_exceptions.PollTimeOut:
            fail('Initial migration timed out')

        try:
            self.mgmt.migrate(id)
        except exceptions.UnprocessableEntity as err:
            assert('status was {}' not in err.message)
        else:
            # If we are trying to test what status is returned when an
            # instance is in a confirm_resize state and another
            # migration is attempted then we also need to
            # assert that an exception is raised when running migrate.
            # If one is not then we aren't able to test what the
            # returned status is in the exception message.
            fail('UnprocessableEntity was not thrown')

    @after_class(always_run=True)
    def tearDown(self):
        while len(self.instances) > 0:
            for id in self.instances:
                try:
                    self.client.instances.delete(id)
                    self.instances.remove(id)
                except exceptions.UnprocessableEntity:
                    sleep(1.0)


def diagnostic_tests_helper(diagnostics):
    print("diagnostics : %r" % diagnostics._info)
    allowed_attrs = ['version', 'fdSize', 'vmSize', 'vmHwm', 'vmRss',
                     'vmPeak', 'threads']
    CheckInstance(None).contains_allowed_attrs(
        diagnostics._info, allowed_attrs,
        msg="Diagnostics")
    assert_true(isinstance(diagnostics.fdSize, int))
    assert_true(isinstance(diagnostics.threads, int))
    assert_true(isinstance(diagnostics.vmHwm, int))
    assert_true(isinstance(diagnostics.vmPeak, int))
    assert_true(isinstance(diagnostics.vmRss, int))
    assert_true(isinstance(diagnostics.vmSize, int))
    actual_version = diagnostics.version
    update_test_conf = CONFIG.values.get("guest-update-test", None)
    if update_test_conf is not None:
        if actual_version == update_test_conf['next-version']:
            return  # This is acceptable but may not match the regex.
    version_pattern = re.compile(r'[a-f0-9]+')
    msg = "Version %s does not match pattern %s." % (actual_version,
                                                     version_pattern)
    assert_true(version_pattern.match(actual_version), msg)
