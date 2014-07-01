#   Copyright (c) 2014 Mirantis, Inc.
#   All Rights Reserved.
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

from trove.common import cfg
from trove.common import exception
from trove.guestagent import dbaas
from trove.guestagent import volume
from trove.guestagent.datastore.mongodb import service as mongo_service
from trove.guestagent.datastore.mongodb import system
from trove.openstack.common import log as logging
from trove.openstack.common.gettextutils import _
from trove.openstack.common import periodic_task


LOG = logging.getLogger(__name__)
CONF = cfg.CONF
MANAGER = CONF.datastore_manager


class Manager(periodic_task.PeriodicTasks):

    def __init__(self):
        self.status = mongo_service.MongoDbAppStatus()
        self.app = mongo_service.MongoDBApp(self.status)

    @periodic_task.periodic_task(ticks_between_runs=3)
    def update_status(self, context):
        """Update the status of the MongoDB service."""
        self.status.update()

    def prepare(self, context, packages, databases, memory_mb, users,
                device_path=None, mount_point=None, backup_info=None,
                config_contents=None, root_password=None, overrides=None):
        """Makes ready DBAAS on a Guest container."""

        LOG.debug("Prepare MongoDB instance")

        self.status.begin_install()
        self.app.install_if_needed(packages)
        self.app.stop_db()
        self.app.clear_storage()
        mount_point = system.MONGODB_MOUNT_POINT
        if device_path:
            device = volume.VolumeDevice(device_path)
            # unmount if device is already mounted
            device.unmount_device(device_path)
            device.format()
            if os.path.exists(system.MONGODB_MOUNT_POINT):
                device.migrate_data(mount_point)
            device.mount(mount_point)
            self.app.update_owner(mount_point)

            LOG.debug("Mounted the volume %(path)s as %(mount)s" %
                      {'path': device_path, "mount": mount_point})

        if mount_point:
            config_contents = self.app.update_config_contents(
                config_contents, {
                    'dbpath': mount_point,
                })

        self.app.start_db_with_conf_changes(config_contents)
        LOG.info(_('"prepare" call has finished.'))

    def restart(self, context):
        self.app.restart()

    def start_db_with_conf_changes(self, context, config_contents):
        self.app.start_db_with_conf_changes(config_contents)

    def stop_db(self, context, do_not_start_on_reboot=False):
        self.app.stop_db(do_not_start_on_reboot=do_not_start_on_reboot)

    def reset_configuration(self, context, configuration):
        self.app.reset_configuration(configuration)

    def get_filesystem_stats(self, context, fs_path):
        """Gets the filesystem stats for the path given."""
        return dbaas.get_filesystem_volume_stats(system.MONGODB_MOUNT_POINT)

    def change_passwords(self, context, users):
        raise exception.DatastoreOperationNotSupported(
            operation='change_passwords', datastore=MANAGER)

    def update_attributes(self, context, username, hostname, user_attrs):
        raise exception.DatastoreOperationNotSupported(
            operation='update_attributes', datastore=MANAGER)

    def create_database(self, context, databases):
        raise exception.DatastoreOperationNotSupported(
            operation='create_database', datastore=MANAGER)

    def create_user(self, context, users):
        raise exception.DatastoreOperationNotSupported(
            operation='create_user', datastore=MANAGER)

    def delete_database(self, context, database):
        raise exception.DatastoreOperationNotSupported(
            operation='delete_database', datastore=MANAGER)

    def delete_user(self, context, user):
        raise exception.DatastoreOperationNotSupported(
            operation='delete_user', datastore=MANAGER)

    def get_user(self, context, username, hostname):
        raise exception.DatastoreOperationNotSupported(
            operation='get_user', datastore=MANAGER)

    def grant_access(self, context, username, hostname, databases):
        raise exception.DatastoreOperationNotSupported(
            operation='grant_access', datastore=MANAGER)

    def revoke_access(self, context, username, hostname, database):
        raise exception.DatastoreOperationNotSupported(
            operation='revoke_access', datastore=MANAGER)

    def list_access(self, context, username, hostname):
        raise exception.DatastoreOperationNotSupported(
            operation='list_access', datastore=MANAGER)

    def list_databases(self, context, limit=None, marker=None,
                       include_marker=False):
        raise exception.DatastoreOperationNotSupported(
            operation='list_databases', datastore=MANAGER)

    def list_users(self, context, limit=None, marker=None,
                   include_marker=False):
        raise exception.DatastoreOperationNotSupported(
            operation='list_users', datastore=MANAGER)

    def enable_root(self, context):
        raise exception.DatastoreOperationNotSupported(
            operation='enable_root', datastore=MANAGER)

    def is_root_enabled(self, context):
        raise exception.DatastoreOperationNotSupported(
            operation='is_root_enabled', datastore=MANAGER)

    def _perform_restore(self, backup_info, context, restore_location, app):
        raise exception.DatastoreOperationNotSupported(
            operation='_perform_restore', datastore=MANAGER)

    def create_backup(self, context, backup_info):
        raise exception.DatastoreOperationNotSupported(
            operation='create_backup', datastore=MANAGER)

    def mount_volume(self, context, device_path=None, mount_point=None):
        device = volume.VolumeDevice(device_path)
        device.mount(mount_point, write_to_fstab=False)
        LOG.debug("Mounted the volume.")

    def unmount_volume(self, context, device_path=None, mount_point=None):
        device = volume.VolumeDevice(device_path)
        device.unmount(mount_point)
        LOG.debug("Unmounted the volume.")

    def resize_fs(self, context, device_path=None, mount_point=None):
        device = volume.VolumeDevice(device_path)
        device.resize_fs(mount_point)
        LOG.debug("Resized the filesystem")

    def update_overrides(self, context, overrides, remove=False):
        raise exception.DatastoreOperationNotSupported(
            operation='update_overrides', datastore=MANAGER)

    def apply_overrides(self, context, overrides):
        raise exception.DatastoreOperationNotSupported(
            operation='apply_overrides', datastore=MANAGER)
