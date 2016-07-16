# Copyright [2015] Hewlett-Packard Development Company, L.P.
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

from mock import DEFAULT
from mock import MagicMock
from mock import patch
from os import path
from testtools.matchers import Is

from trove.common.exception import DatastoreOperationNotSupported
from trove.common import instance as rd_instance
from trove.guestagent.common import configuration
from trove.guestagent.common.configuration import ImportOverrideStrategy
from trove.guestagent.common import operating_system
from trove.guestagent.datastore.experimental.vertica.manager import Manager
from trove.guestagent.datastore.experimental.vertica.service import (
    VerticaAppStatus)
from trove.guestagent.datastore.experimental.vertica.service import VerticaApp
from trove.guestagent.datastore.experimental.vertica import system
from trove.guestagent import dbaas
from trove.guestagent import volume
from trove.guestagent.volume import VolumeDevice
from trove.tests.unittests.guestagent.test_datastore_manager import \
    DatastoreManagerTest


class GuestAgentManagerTest(DatastoreManagerTest):

    @patch.object(ImportOverrideStrategy, '_initialize_import_directory')
    @patch.multiple(operating_system, exists=DEFAULT, write_file=DEFAULT,
                    chown=DEFAULT, chmod=DEFAULT)
    def setUp(self, *args, **kwargs):
        super(GuestAgentManagerTest, self).setUp('vertica')
        self.manager = Manager()
        self.origin_format = volume.VolumeDevice.format
        self.origin_migrate_data = volume.VolumeDevice.migrate_data
        self.origin_mount = volume.VolumeDevice.mount
        self.origin_unmount = volume.VolumeDevice.unmount
        self.origin_mount_points = volume.VolumeDevice.mount_points
        self.origin_set_read = volume.VolumeDevice.set_readahead_size
        self.origin_install_vertica = VerticaApp.install_vertica
        self.origin_create_db = VerticaApp.create_db
        self.origin_stop_db = VerticaApp.stop_db
        self.origin_start_db = VerticaApp.start_db
        self.origin_restart = VerticaApp.restart
        self.origin_install_if = VerticaApp.install_if_needed
        self.origin_enable_root = VerticaApp.enable_root
        self.origin_is_root_enabled = VerticaApp.is_root_enabled
        self.origin_prepare_for_install_vertica = (
            VerticaApp.prepare_for_install_vertica)
        self.origin_add_udls = VerticaApp.add_udls

    def tearDown(self):
        super(GuestAgentManagerTest, self).tearDown()
        volume.VolumeDevice.format = self.origin_format
        volume.VolumeDevice.migrate_data = self.origin_migrate_data
        volume.VolumeDevice.mount = self.origin_mount
        volume.VolumeDevice.unmount = self.origin_unmount
        volume.VolumeDevice.mount_points = self.origin_mount_points
        volume.VolumeDevice.set_readahead_size = self.origin_set_read
        VerticaApp.create_db = self.origin_create_db
        VerticaApp.install_vertica = self.origin_install_vertica
        VerticaApp.stop_db = self.origin_stop_db
        VerticaApp.start_db = self.origin_start_db
        VerticaApp.restart = self.origin_restart
        VerticaApp.install_if_needed = self.origin_install_if
        VerticaApp.enable_root = self.origin_enable_root
        VerticaApp.is_root_enabled = self.origin_is_root_enabled
        VerticaApp.prepare_for_install_vertica = (
            self.origin_prepare_for_install_vertica)
        VerticaApp.add_udls = self.origin_add_udls

    def test_update_status(self):
        mock_status = MagicMock()
        self.manager.appStatus = mock_status
        self.manager.update_status(self.context)
        mock_status.update.assert_any_call()

    @patch.object(path, 'exists', MagicMock())
    @patch.object(configuration.ConfigurationManager, 'save_configuration')
    def _prepare_dynamic(self, packages,
                         config_content='MockContent', device_path='/dev/vdb',
                         backup_id=None,
                         overrides=None, is_mounted=False):
        # covering all outcomes is starting to cause trouble here
        expected_vol_count = 1 if device_path else 0
        if not backup_id:
            backup_info = {'id': backup_id,
                           'location': 'fake-location',
                           'type': 'InnoBackupEx',
                           'checksum': 'fake-checksum',
                           }

        mock_status = MagicMock()
        self.manager.appStatus = mock_status

        mock_status.begin_install = MagicMock(return_value=None)
        volume.VolumeDevice.format = MagicMock(return_value=None)
        volume.VolumeDevice.migrate_data = MagicMock(return_value=None)
        volume.VolumeDevice.mount = MagicMock(return_value=None)
        mount_points = []
        if is_mounted:
            mount_points = ['/mnt']
        VolumeDevice.mount_points = MagicMock(return_value=mount_points)
        VolumeDevice.unmount = MagicMock(return_value=None)

        VerticaApp.install_if_needed = MagicMock(return_value=None)
        VerticaApp.install_vertica = MagicMock(return_value=None)
        VerticaApp.create_db = MagicMock(return_value=None)
        VerticaApp.prepare_for_install_vertica = MagicMock(return_value=None)
        VerticaApp.add_udls = MagicMock()
        # invocation
        self.manager.prepare(context=self.context, packages=packages,
                             config_contents=config_content,
                             databases=None,
                             memory_mb='2048', users=None,
                             device_path=device_path,
                             mount_point="/var/lib/vertica",
                             backup_info=backup_info,
                             overrides=None,
                             cluster_config=None)

        self.assertEqual(expected_vol_count, VolumeDevice.format.call_count)
        self.assertEqual(expected_vol_count,
                         VolumeDevice.migrate_data.call_count)
        self.assertEqual(expected_vol_count,
                         VolumeDevice.mount_points.call_count)
        if is_mounted:
            self.assertEqual(1, VolumeDevice.unmount.call_count)
        else:
            self.assertEqual(0, VolumeDevice.unmount.call_count)

        VerticaApp.install_if_needed.assert_any_call(packages)
        VerticaApp.prepare_for_install_vertica.assert_any_call()
        VerticaApp.install_vertica.assert_any_call()
        VerticaApp.create_db.assert_any_call()
        VerticaApp.add_udls.assert_any_call()

    def test_prepare_pkg(self):
        self._prepare_dynamic(['vertica'])

    def test_prepare_no_pkg(self):
        self._prepare_dynamic([])

    def test_restart(self):
        mock_status = MagicMock()
        self.manager.appStatus = mock_status
        VerticaApp.restart = MagicMock(return_value=None)
        # invocation
        self.manager.restart(self.context)
        # verification/assertion
        VerticaApp.restart.assert_any_call()

    def test_stop_db(self):
        mock_status = MagicMock()
        self.manager.appStatus = mock_status
        VerticaApp.stop_db = MagicMock(return_value=None)
        # invocation
        self.manager.stop_db(self.context)
        # verification/assertion
        VerticaApp.stop_db.assert_any_call(do_not_start_on_reboot=False)

    @patch.object(VerticaApp, 'install_vertica')
    @patch.object(VerticaApp, '_export_conf_to_members')
    @patch.object(VerticaApp, 'create_db')
    @patch.object(VerticaApp, 'add_udls')
    def test_install_cluster(self, mock_udls, mock_install, mock_export,
                             mock_create_db):
        members = ['test1', 'test2']
        self.manager.install_cluster(self.context, members)
        mock_install.assert_called_with('test1,test2')
        mock_export.assert_called_with(members)
        mock_create_db.assert_called_with('test1,test2')
        mock_udls.assert_any_call()

    @patch.object(VerticaAppStatus, 'set_status')
    @patch.object(VerticaApp, 'install_cluster',
                  side_effect=RuntimeError("Boom!"))
    @patch('trove.guestagent.datastore.experimental.vertica.manager.LOG')
    def test_install_cluster_failure(self, mock_logging,
                                     mock_install, mock_set_status):
        members = ["test1", "test2"]
        self.assertRaises(RuntimeError, self.manager.install_cluster,
                          self.context, members)
        mock_set_status.assert_called_with(rd_instance.ServiceStatuses.FAILED)

    @patch.object(VerticaApp, '_get_database_password')
    @patch.object(path, 'isfile')
    @patch.object(system, 'exec_vsql_command')
    def test_add_udls(self, mock_vsql, mock_isfile, mock_pwd):
        mock_vsql.return_value = (None, None)
        password = 'password'
        mock_pwd.return_value = password
        mock_isfile.return_value = True
        self.manager.app.add_udls()
        mock_vsql.assert_any_call(
            password,
            "CREATE LIBRARY curllib AS "
            "'/opt/vertica/sdk/examples/build/cURLLib.so'"
        )
        mock_vsql.assert_any_call(
            password,
            "CREATE SOURCE curl AS LANGUAGE 'C++' NAME 'CurlSourceFactory' "
            "LIBRARY curllib"
        )

    @patch.object(volume.VolumeDevice, 'mount_points', return_value=[])
    @patch.object(volume.VolumeDevice, 'unmount_device', return_value=None)
    @patch.object(volume.VolumeDevice, 'mount', return_value=None)
    @patch.object(volume.VolumeDevice, 'migrate_data', return_value=None)
    @patch.object(volume.VolumeDevice, 'format', return_value=None)
    @patch.object(VerticaApp, 'prepare_for_install_vertica')
    @patch.object(VerticaApp, 'install_if_needed')
    @patch.object(VerticaApp, 'add_udls')
    @patch.object(VerticaAppStatus, 'begin_install')
    def _prepare_method(self, instance_id, instance_type, *args):
        cluster_config = {"id": instance_id,
                          "instance_type": instance_type}

        # invocation
        self.manager.prepare(context=self.context, databases=None,
                             packages=['vertica'],
                             memory_mb='2048', users=None,
                             mount_point='/var/lib/vertica',
                             overrides=None,
                             cluster_config=cluster_config)

    @patch.object(VerticaAppStatus, 'set_status')
    def test_prepare_member(self, mock_set_status):
        self._prepare_method("test-instance-3", "member")
        mock_set_status.assert_called_with(
            rd_instance.ServiceStatuses.INSTANCE_READY, force=True)

    def test_rpc_ping(self):
        output = self.manager.rpc_ping(self.context)
        self.assertTrue(output)

    @patch.object(VerticaAppStatus, 'set_status')
    @patch('trove.guestagent.datastore.manager.LOG')
    def test_prepare_invalid_cluster_config(self, mock_logging,
                                            mock_set_status):
        self.assertRaises(RuntimeError,
                          self._prepare_method,
                          "test-instance-3", "query_router")
        mock_set_status.assert_called_with(
            rd_instance.ServiceStatuses.FAILED, force=True)

    def test_get_filesystem_stats(self):
        with patch.object(dbaas, 'get_filesystem_volume_stats'):
            self.manager.get_filesystem_stats(self.context, '/var/lib/vertica')
            dbaas.get_filesystem_volume_stats.assert_any_call(
                '/var/lib/vertica')

    def test_mount_volume(self):
        with patch.object(volume.VolumeDevice, 'mount', return_value=None):
            self.manager.mount_volume(self.context,
                                      device_path='/dev/vdb',
                                      mount_point='/var/lib/vertica')
            test_mount = volume.VolumeDevice.mount.call_args_list[0]
            test_mount.assert_called_with('/var/lib/vertica', False)

    def test_unmount_volume(self):
        with patch.object(volume.VolumeDevice, 'unmount', return_value=None):
            self.manager.unmount_volume(self.context, device_path='/dev/vdb')
            test_unmount = volume.VolumeDevice.unmount.call_args_list[0]
            test_unmount.assert_called_with('/var/lib/vertica')

    def test_resize_fs(self):
        with patch.object(volume.VolumeDevice, 'resize_fs', return_value=None):
            self.manager.resize_fs(self.context, device_path='/dev/vdb')
            test_resize_fs = volume.VolumeDevice.resize_fs.call_args_list[0]
            test_resize_fs.assert_called_with('/var/lib/vertica')

    @patch.object(operating_system, 'write_file')
    def test_cluster_complete(self, mock_write_file):
        mock_set_status = MagicMock()
        self.manager.appStatus.set_status = mock_set_status
        self.manager.appStatus._get_actual_db_status = MagicMock(
            return_value=rd_instance.ServiceStatuses.RUNNING)
        self.manager.cluster_complete(self.context)
        mock_set_status.assert_called_with(
            rd_instance.ServiceStatuses.RUNNING, force=True)

    def test_get_public_keys(self):
        with patch.object(VerticaApp, 'get_public_keys',
                          return_value='some_key'):
            test_key = self.manager.get_public_keys(self.context, 'test_user')
            self.assertEqual('some_key', test_key)

    def test_authorize_public_keys(self):
        with patch.object(VerticaApp, 'authorize_public_keys',
                          return_value=None):
            self.manager.authorize_public_keys(self.context,
                                               'test_user',
                                               'some_key')
            VerticaApp.authorize_public_keys.assert_any_call(
                'test_user', 'some_key')

    def test_start_db_with_conf_changes(self):
        with patch.object(VerticaApp, 'start_db_with_conf_changes'):
            self.manager.start_db_with_conf_changes(self.context, 'something')
            VerticaApp.start_db_with_conf_changes.assert_any_call('something')

    def test_change_passwords(self):
        self.assertRaises(DatastoreOperationNotSupported,
                          self.manager.change_passwords,
                          self.context, None)

    def test_update_attributes(self):
        self.assertRaises(DatastoreOperationNotSupported,
                          self.manager.update_attributes,
                          self.context, 'test_user', '%', {'name': 'new_user'})

    def test_create_database(self):
        self.assertRaises(DatastoreOperationNotSupported,
                          self.manager.create_database,
                          self.context, [{'name': 'test_db'}])

    def test_create_user(self):
        self.assertRaises(DatastoreOperationNotSupported,
                          self.manager.create_user,
                          self.context, [{'name': 'test_user'}])

    def test_delete_database(self):
        self.assertRaises(DatastoreOperationNotSupported,
                          self.manager.delete_database,
                          self.context, [{'name': 'test_db'}])

    def test_delete_user(self):
        self.assertRaises(DatastoreOperationNotSupported,
                          self.manager.delete_user,
                          self.context, [{'name': 'test_user'}])

    def test_get_user(self):
        self.assertRaises(DatastoreOperationNotSupported,
                          self.manager.get_user,
                          self.context, 'test_user', '%')

    def test_grant_access(self):
        self.assertRaises(DatastoreOperationNotSupported,
                          self.manager.grant_access,
                          self.context, 'test_user', '%', [{'name': 'test_db'}]
                          )

    def test_revoke_access(self):
        self.assertRaises(DatastoreOperationNotSupported,
                          self.manager.revoke_access,
                          self.context, 'test_user', '%', [{'name': 'test_db'}]
                          )

    def test_list_access(self):
        self.assertRaises(DatastoreOperationNotSupported,
                          self.manager.list_access,
                          self.context, 'test_user', '%')

    def test_list_databases(self):
        self.assertRaises(DatastoreOperationNotSupported,
                          self.manager.list_databases,
                          self.context)

    def test_list_users(self):
        self.assertRaises(DatastoreOperationNotSupported,
                          self.manager.list_users,
                          self.context)

    def test_enable_root(self):
        VerticaApp.enable_root = MagicMock(return_value='user_id_stuff')
        user_id = self.manager.enable_root_with_password(self.context)
        self.assertThat(user_id, Is('user_id_stuff'))

    def test_is_root_enabled(self):
        VerticaApp.is_root_enabled = MagicMock(return_value=True)
        is_enabled = self.manager.is_root_enabled(self.context)
        self.assertThat(is_enabled, Is(True))

    def test_create_backup(self):
        self.assertRaises(DatastoreOperationNotSupported,
                          self.manager.create_backup,
                          self.context, {})
