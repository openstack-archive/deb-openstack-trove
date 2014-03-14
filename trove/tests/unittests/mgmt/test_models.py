# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
#
from mockito import mock, when, verify, unstub, any
from testtools import TestCase
from testtools.matchers import Equals, Is, Not

from novaclient.v1_1 import Client
from novaclient.v1_1.flavors import FlavorManager, Flavor
from novaclient.v1_1.servers import Server, ServerManager
from oslo.config.cfg import ConfigOpts
from trove.backup.models import Backup
from trove.common.context import TroveContext
from trove.common import instance as rd_instance
from trove.datastore import models as datastore_models
from trove.db.models import DatabaseModelBase
from trove.instance.models import DBInstance
from trove.instance.models import InstanceServiceStatus
from trove.instance.tasks import InstanceTasks
import trove.extensions.mgmt.instances.models as mgmtmodels
from trove.openstack.common.notifier import api as notifier
from trove.common import remote
from trove.tests.util import test_config


class MockMgmtInstanceTest(TestCase):
    def setUp(self):
        super(MockMgmtInstanceTest, self).setUp()
        self.context = TroveContext()
        self.context.auth_token = 'some_secret_password'
        self.client = mock(Client)
        self.server_mgr = mock(ServerManager)
        self.client.servers = self.server_mgr
        self.flavor_mgr = mock(FlavorManager)
        self.client.flavors = self.flavor_mgr
        when(remote).create_admin_nova_client(self.context).thenReturn(
            self.client)
        when(ConfigOpts)._get('host').thenReturn('test_host')
        when(ConfigOpts)._get('exists_notification_ticks').thenReturn(1)
        when(ConfigOpts)._get('report_interval').thenReturn(20)
        when(ConfigOpts)._get('notification_service_id').thenReturn(
            {'mysql': '123'})

    def tearDown(self):
        super(MockMgmtInstanceTest, self).tearDown()
        unstub()

    @staticmethod
    def build_db_instance(status, task_status=InstanceTasks.DELETING):
        return DBInstance(task_status,
                          created='xyz',
                          name='test_name',
                          id='1',
                          flavor_id='flavor_1',
                          datastore_version_id=
                          test_config.dbaas_datastore_version_id,
                          compute_instance_id='compute_id_1',
                          server_id='server_id_1',
                          tenant_id='tenant_id_1',
                          server_status=status)


class TestNotificationTransformer(MockMgmtInstanceTest):
    def test_tranformer(self):
        transformer = mgmtmodels.NotificationTransformer(context=self.context)
        status = rd_instance.ServiceStatuses.BUILDING.api_status
        db_instance = MockMgmtInstanceTest.build_db_instance(
            status, InstanceTasks.BUILDING)

        when(DatabaseModelBase).find_all(deleted=False).thenReturn(
            [db_instance])
        stub_dsv_db_info = mock(datastore_models.DBDatastoreVersion)
        stub_dsv_db_info.id = "test_datastore_version"
        stub_dsv_db_info.datastore_id = "mysql_test_version"
        stub_dsv_db_info.name = "test_datastore_name"
        stub_dsv_db_info.image_id = "test_datastore_image_id"
        stub_dsv_db_info.packages = "test_datastore_pacakges"
        stub_dsv_db_info.active = 1
        stub_dsv_db_info.manager = "mysql"
        stub_datastore_version = datastore_models.DatastoreVersion(
            stub_dsv_db_info)
        when(DatabaseModelBase).find_by(id=any()).thenReturn(
            stub_datastore_version)

        when(DatabaseModelBase).find_by(instance_id='1').thenReturn(
            InstanceServiceStatus(rd_instance.ServiceStatuses.BUILDING))

        payloads = transformer()
        self.assertIsNotNone(payloads)
        self.assertThat(len(payloads), Equals(1))
        payload = payloads[0]
        self.assertThat(payload['audit_period_beginning'], Not(Is(None)))
        self.assertThat(payload['audit_period_ending'], Not(Is(None)))
        self.assertThat(payload['state'], Equals(status.lower()))

    def test_get_service_id(self):
        id_map = {
            'mysql': '123',
            'percona': 'abc'
        }
        transformer = mgmtmodels.NotificationTransformer(context=self.context)
        self.assertThat(transformer._get_service_id('mysql', id_map),
                        Equals('123'))

    def test_get_service_id_unknown(self):
        id_map = {
            'mysql': '123',
            'percona': 'abc'
        }
        transformer = mgmtmodels.NotificationTransformer(context=self.context)
        self.assertThat(transformer._get_service_id('m0ng0', id_map),
                        Equals('unknown-service-id-error'))


class TestNovaNotificationTransformer(MockMgmtInstanceTest):
    def test_transformer_cache(self):
        flavor = mock(Flavor)
        flavor.name = 'db.small'
        when(self.flavor_mgr).get('flavor_1').thenReturn(flavor)
        transformer = mgmtmodels.NovaNotificationTransformer(
            context=self.context)
        transformer2 = mgmtmodels.NovaNotificationTransformer(
            context=self.context)
        self.assertThat(transformer._flavor_cache,
                        Not(Is(transformer2._flavor_cache)))

    def test_lookup_flavor(self):
        flavor = mock(Flavor)
        flavor.name = 'flav_1'
        when(self.flavor_mgr).get('1').thenReturn(flavor)
        transformer = mgmtmodels.NovaNotificationTransformer(
            context=self.context)
        self.assertThat(transformer._lookup_flavor('1'), Equals(flavor.name))
        self.assertThat(transformer._lookup_flavor('2'), Equals('unknown'))

    def test_tranformer(self):
        status = rd_instance.ServiceStatuses.BUILDING.api_status
        db_instance = MockMgmtInstanceTest.build_db_instance(
            status, task_status=InstanceTasks.BUILDING)

        stub_dsv_db_info = mock(datastore_models.DBDatastoreVersion)
        stub_dsv_db_info.id = "test_datastore_version"
        stub_dsv_db_info.datastore_id = "mysql_test_version"
        stub_dsv_db_info.name = "test_datastore_name"
        stub_dsv_db_info.image_id = "test_datastore_image_id"
        stub_dsv_db_info.packages = "test_datastore_pacakges"
        stub_dsv_db_info.active = 1
        stub_dsv_db_info.manager = "mysql"
        stub_datastore_version = datastore_models.DatastoreVersion(
            stub_dsv_db_info)
        when(DatabaseModelBase).find_by(id=any()).thenReturn(
            stub_datastore_version)

        server = mock(Server)
        server.user_id = 'test_user_id'
        mgmt_instance = mgmtmodels.SimpleMgmtInstance(self.context,
                                                      db_instance,
                                                      server,
                                                      None)
        when(mgmtmodels).load_mgmt_instances(
            self.context,
            deleted=False,
            client=self.client).thenReturn(
                [mgmt_instance])
        flavor = mock(Flavor)
        flavor.name = 'db.small'
        when(self.flavor_mgr).get('flavor_1').thenReturn(flavor)

        # invocation
        transformer = mgmtmodels.NovaNotificationTransformer(
            context=self.context)
        payloads = transformer()
        # assertions
        self.assertIsNotNone(payloads)
        self.assertThat(len(payloads), Equals(1))
        payload = payloads[0]
        self.assertThat(payload['audit_period_beginning'], Not(Is(None)))
        self.assertThat(payload['audit_period_ending'], Not(Is(None)))
        self.assertThat(payload['state'], Equals(status.lower()))
        self.assertThat(payload['instance_type'], Equals('db.small'))
        self.assertThat(payload['instance_type_id'], Equals('flavor_1'))
        self.assertThat(payload['user_id'], Equals('test_user_id'))
        self.assertThat(payload['service_id'], Equals('123'))

    def test_tranformer_invalid_datastore_manager(self):
        status = rd_instance.ServiceStatuses.BUILDING.api_status
        db_instance = MockMgmtInstanceTest.build_db_instance(
            status, task_status=InstanceTasks.BUILDING)

        server = mock(Server)
        server.user_id = 'test_user_id'
        stub_datastore_version = mock()
        stub_datastore_version.id = "stub_datastore_version"
        stub_datastore_version.manager = "m0ng0"
        when(datastore_models.
             DatastoreVersion).load(any(), any()).thenReturn(
                 stub_datastore_version)
        when(datastore_models.
             DatastoreVersion).load_by_uuid(any()).thenReturn(
                 stub_datastore_version)

        stub_datastore = mock()
        stub_datastore.default_datastore_version = "stub_datastore_version"
        when(datastore_models.
             Datastore).load(any()).thenReturn(stub_datastore)
        mgmt_instance = mgmtmodels.SimpleMgmtInstance(self.context,
                                                      db_instance,
                                                      server,
                                                      None)
        when(mgmtmodels).load_mgmt_instances(
            self.context,
            deleted=False,
            client=self.client).thenReturn(
                [mgmt_instance])
        flavor = mock(Flavor)
        flavor.name = 'db.small'
        when(self.flavor_mgr).get('flavor_1').thenReturn(flavor)

        # invocation
        transformer = mgmtmodels.NovaNotificationTransformer(
            context=self.context)
        payloads = transformer()
        # assertions
        self.assertIsNotNone(payloads)
        self.assertThat(len(payloads), Equals(1))
        payload = payloads[0]
        self.assertThat(payload['audit_period_beginning'], Not(Is(None)))
        self.assertThat(payload['audit_period_ending'], Not(Is(None)))
        self.assertThat(payload['state'], Equals(status.lower()))
        self.assertThat(payload['instance_type'], Equals('db.small'))
        self.assertThat(payload['instance_type_id'], Equals('flavor_1'))
        self.assertThat(payload['user_id'], Equals('test_user_id'))
        self.assertThat(payload['service_id'],
                        Equals('unknown-service-id-error'))

    def test_tranformer_shutdown_instance(self):
        status = rd_instance.ServiceStatuses.SHUTDOWN.api_status
        db_instance = self.build_db_instance(status)

        server = mock(Server)
        server.user_id = 'test_user_id'
        mgmt_instance = mgmtmodels.SimpleMgmtInstance(self.context,
                                                      db_instance,
                                                      server,
                                                      None)
        when(Backup).running('1').thenReturn(None)
        self.assertThat(mgmt_instance.status, Equals('SHUTDOWN'))
        when(mgmtmodels).load_mgmt_instances(
            self.context,
            deleted=False,
            client=self.client).thenReturn(
                [mgmt_instance])
        flavor = mock(Flavor)
        flavor.name = 'db.small'
        when(self.flavor_mgr).get('flavor_1').thenReturn(flavor)
        # invocation
        transformer = mgmtmodels.NovaNotificationTransformer(
            context=self.context)
        payloads = transformer()
        # assertion that SHUTDOWN instances are not reported
        self.assertIsNotNone(payloads)
        self.assertThat(len(payloads), Equals(0))

    def test_tranformer_no_nova_instance(self):
        status = rd_instance.ServiceStatuses.SHUTDOWN.api_status
        db_instance = MockMgmtInstanceTest.build_db_instance(status)

        mgmt_instance = mgmtmodels.SimpleMgmtInstance(self.context,
                                                      db_instance,
                                                      None,
                                                      None)
        when(Backup).running('1').thenReturn(None)
        self.assertThat(mgmt_instance.status, Equals('SHUTDOWN'))
        when(mgmtmodels).load_mgmt_instances(
            self.context,
            deleted=False,
            client=self.client).thenReturn(
                [mgmt_instance])
        flavor = mock(Flavor)
        flavor.name = 'db.small'
        when(self.flavor_mgr).get('flavor_1').thenReturn(flavor)
        # invocation
        transformer = mgmtmodels.NovaNotificationTransformer(
            context=self.context)
        payloads = transformer()
        # assertion that SHUTDOWN instances are not reported
        self.assertIsNotNone(payloads)
        self.assertThat(len(payloads), Equals(0))

    def test_tranformer_flavor_cache(self):
        status = rd_instance.ServiceStatuses.BUILDING.api_status
        db_instance = MockMgmtInstanceTest.build_db_instance(
            status, InstanceTasks.BUILDING)

        server = mock(Server)
        server.user_id = 'test_user_id'
        mgmt_instance = mgmtmodels.SimpleMgmtInstance(self.context,
                                                      db_instance,
                                                      server,
                                                      None)
        when(mgmtmodels).load_mgmt_instances(
            self.context,
            deleted=False,
            client=self.client).thenReturn(
                [mgmt_instance])
        flavor = mock(Flavor)
        flavor.name = 'db.small'
        when(self.flavor_mgr).get('flavor_1').thenReturn(flavor)
        transformer = mgmtmodels.NovaNotificationTransformer(
            context=self.context)
        transformer()
        # call twice ensure client.flavor invoked once
        payloads = transformer()
        self.assertIsNotNone(payloads)
        self.assertThat(len(payloads), Equals(1))
        payload = payloads[0]
        self.assertThat(payload['audit_period_beginning'], Not(Is(None)))
        self.assertThat(payload['audit_period_ending'], Not(Is(None)))
        self.assertThat(payload['state'], Equals(status.lower()))
        self.assertThat(payload['instance_type'], Equals('db.small'))
        self.assertThat(payload['instance_type_id'], Equals('flavor_1'))
        self.assertThat(payload['user_id'], Equals('test_user_id'))
        # ensure cache was used to get flavor second time
        verify(self.flavor_mgr).get('flavor_1')


class TestMgmtInstanceTasks(MockMgmtInstanceTest):
    def test_public_exists_events(self):
        status = rd_instance.ServiceStatuses.BUILDING.api_status
        db_instance = MockMgmtInstanceTest.build_db_instance(
            status, task_status=InstanceTasks.BUILDING)

        server = mock(Server)
        server.user_id = 'test_user_id'
        mgmt_instance = mgmtmodels.SimpleMgmtInstance(self.context,
                                                      db_instance,
                                                      server,
                                                      None)
        when(mgmtmodels).load_mgmt_instances(
            self.context,
            deleted=False,
            client=self.client).thenReturn(
                [mgmt_instance, mgmt_instance])
        flavor = mock(Flavor)
        flavor.name = 'db.small'
        when(self.flavor_mgr).get('flavor_1').thenReturn(flavor)
        self.assertThat(self.context.auth_token, Is('some_secret_password'))
        when(notifier).notify(self.context,
                              any(str),
                              'trove.instance.exists',
                              'INFO',
                              any(dict)).thenReturn(None)
        # invocation
        mgmtmodels.publish_exist_events(
            mgmtmodels.NovaNotificationTransformer(context=self.context),
            self.context)
        # assertion
        verify(notifier, times=2).notify(self.context,
                                         any(str),
                                         'trove.instance.exists',
                                         'INFO',
                                         any(dict))
        self.assertThat(self.context.auth_token, Is(None))
