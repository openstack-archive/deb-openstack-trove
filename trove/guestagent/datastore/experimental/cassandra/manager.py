#  Copyright 2013 Mirantis Inc.
#  All Rights Reserved.
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

import os

from oslo_log import log as logging

from trove.common import cfg
from trove.common.i18n import _
from trove.common import instance as trove_instance
from trove.common.notification import EndNotification
from trove.guestagent import backup
from trove.guestagent.datastore.experimental.cassandra import service
from trove.guestagent.datastore import manager
from trove.guestagent import guest_log
from trove.guestagent import volume


LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class Manager(manager.Manager):

    GUEST_LOG_DEFS_SYSTEM_LABEL = 'system'

    def __init__(self, manager_name='cassandra'):
        super(Manager, self).__init__(manager_name)
        self._app = None
        self._admin = None

    @property
    def status(self):
        return self.app.status

    @property
    def app(self):
        if self._app is None:
            self._app = self.build_app()
        return self._app

    def build_app(self):
        return service.CassandraApp()

    @property
    def admin(self):
        if self._admin is None:
            self._admin = self.app.build_admin()
        return self._admin

    @property
    def configuration_manager(self):
        return self.app.configuration_manager

    @property
    def datastore_log_defs(self):
        system_log_file = self.validate_log_file(
            self.app.cassandra_system_log_file, self.app.cassandra_owner)
        return {
            self.GUEST_LOG_DEFS_SYSTEM_LABEL: {
                self.GUEST_LOG_TYPE_LABEL: guest_log.LogType.USER,
                self.GUEST_LOG_USER_LABEL: self.app.cassandra_owner,
                self.GUEST_LOG_FILE_LABEL: system_log_file
            }
        }

    def guest_log_enable(self, context, log_name, disable):
        if disable:
            LOG.debug("Disabling system log.")
            self.app.set_logging_level('OFF')
        else:
            log_level = CONF.get(self.manager_name).get('system_log_level')
            LOG.debug("Enabling system log with logging level: %s" % log_level)
            self.app.set_logging_level(log_level)

        return False

    def restart(self, context):
        self.app.restart()

    def start_db_with_conf_changes(self, context, config_contents):
        self.app.start_db_with_conf_changes(config_contents)

    def stop_db(self, context, do_not_start_on_reboot=False):
        self.app.stop_db(do_not_start_on_reboot=do_not_start_on_reboot)

    def reset_configuration(self, context, configuration):
        self.app.reset_configuration(configuration)

    def do_prepare(self, context, packages, databases, memory_mb, users,
                   device_path, mount_point, backup_info,
                   config_contents, root_password, overrides,
                   cluster_config, snapshot):
        """This is called from prepare in the base class."""
        self.app.install_if_needed(packages)
        self.app.init_storage_structure(mount_point)

        if config_contents or device_path or backup_info:

            # FIXME(pmalik) Once the cassandra bug
            # https://issues.apache.org/jira/browse/CASSANDRA-2356
            # is fixed, this code may have to be revisited.
            #
            # Cassandra generates system keyspaces on the first start.
            # The stored properties include the 'cluster_name', which once
            # saved cannot be easily changed without removing the system
            # tables. It is crucial that the service does not boot up in
            # the middle of the configuration procedure.
            # We wait here for the service to come up, stop it properly and
            # remove the generated keyspaces before proceeding with
            # configuration. If it does not start up within the time limit
            # we assume it is not going to and proceed with configuration
            # right away.
            LOG.debug("Waiting for database first boot.")
            if (self.app.status.wait_for_real_status_to_change_to(
                    trove_instance.ServiceStatuses.RUNNING,
                    CONF.state_change_wait_time,
                    False)):
                LOG.debug("Stopping database prior to initial configuration.")
                self.app.stop_db()
                self.app._remove_system_tables()

            LOG.debug("Starting initial configuration.")
            if config_contents:
                LOG.debug("Applying configuration.")
                self.app.configuration_manager.save_configuration(
                    config_contents)
                cluster_name = None
                if cluster_config:
                    cluster_name = cluster_config.get('id', None)
                self.app.apply_initial_guestagent_configuration(
                    cluster_name=cluster_name)

            if cluster_config:
                self.app.write_cluster_topology(
                    cluster_config['dc'], cluster_config['rack'],
                    prefer_local=True)

            if device_path:
                LOG.debug("Preparing data volume.")
                device = volume.VolumeDevice(device_path)
                # unmount if device is already mounted
                device.unmount_device(device_path)
                device.format()
                if os.path.exists(mount_point):
                    # rsync exiting data
                    LOG.debug("Migrating existing data.")
                    device.migrate_data(mount_point)
                # mount the volume
                LOG.debug("Mounting new volume.")
                device.mount(mount_point)

            if not cluster_config:
                if backup_info:
                    self._perform_restore(backup_info, context, mount_point)

                LOG.debug("Starting database with configuration changes.")
                self.app.start_db(update_db=False)

                if not self.app.has_user_config():
                    LOG.debug("Securing superuser access.")
                    self.app.secure()
                    self.app.restart()

            self._admin = self.app.build_admin()

        if not cluster_config and self.is_root_enabled(context):
            self.status.report_root(context, self.app.default_superuser_name)

    def change_passwords(self, context, users):
        with EndNotification(context):
            self.admin.change_passwords(context, users)

    def update_attributes(self, context, username, hostname, user_attrs):
        with EndNotification(context):
            self.admin.update_attributes(context, username, hostname,
                                         user_attrs)

    def create_database(self, context, databases):
        with EndNotification(context):
            self.admin.create_database(context, databases)

    def create_user(self, context, users):
        with EndNotification(context):
            self.admin.create_user(context, users)

    def delete_database(self, context, database):
        with EndNotification(context):
            self.admin.delete_database(context, database)

    def delete_user(self, context, user):
        with EndNotification(context):
            self.admin.delete_user(context, user)

    def get_user(self, context, username, hostname):
        return self.admin.get_user(context, username, hostname)

    def grant_access(self, context, username, hostname, databases):
        self.admin.grant_access(context, username, hostname, databases)

    def revoke_access(self, context, username, hostname, database):
        self.admin.revoke_access(context, username, hostname, database)

    def list_access(self, context, username, hostname):
        return self.admin.list_access(context, username, hostname)

    def list_databases(self, context, limit=None, marker=None,
                       include_marker=False):
        return self.admin.list_databases(context, limit, marker,
                                         include_marker)

    def list_users(self, context, limit=None, marker=None,
                   include_marker=False):
        return self.admin.list_users(context, limit, marker, include_marker)

    def enable_root(self, context):
        return self.app.enable_root()

    def enable_root_with_password(self, context, root_password=None):
        return self.app.enable_root(root_password=root_password)

    def disable_root(self, context):
        self.app.enable_root(root_password=None)

    def is_root_enabled(self, context):
        return self.app.is_root_enabled()

    def _perform_restore(self, backup_info, context, restore_location):
        LOG.info(_("Restoring database from backup %s.") % backup_info['id'])
        try:
            backup.restore(context, backup_info, restore_location)
            self.app._apply_post_restore_updates(backup_info)
        except Exception as e:
            LOG.error(e)
            LOG.error(_("Error performing restore from backup %s.") %
                      backup_info['id'])
            self.app.status.set_status(trove_instance.ServiceStatuses.FAILED)
            raise
        LOG.info(_("Restored database successfully."))

    def create_backup(self, context, backup_info):
        """
        Entry point for initiating a backup for this instance.
        The call currently blocks guestagent until the backup is finished.

        :param backup_info: a dictionary containing the db instance id of the
                            backup task, location, type, and other data.
        """

        with EndNotification(context):
            backup.backup(context, backup_info)

    def update_overrides(self, context, overrides, remove=False):
        LOG.debug("Updating overrides.")
        if remove:
            self.app.remove_overrides()
        else:
            self.app.update_overrides(context, overrides, remove)

    def apply_overrides(self, context, overrides):
        """Configuration changes are made in the config YAML file and
        require restart, so this is a no-op.
        """
        pass

    def get_data_center(self, context):
        return self.app.get_data_center()

    def get_rack(self, context):
        return self.app.get_rack()

    def set_seeds(self, context, seeds):
        self.app.set_seeds(seeds)

    def get_seeds(self, context):
        return self.app.get_seeds()

    def set_auto_bootstrap(self, context, enabled):
        self.app.set_auto_bootstrap(enabled)

    def node_cleanup_begin(self, context):
        self.app.node_cleanup_begin()

    def node_cleanup(self, context):
        self.app.node_cleanup()

    def node_decommission(self, context):
        self.app.node_decommission()

    def cluster_secure(self, context, password):
        os_admin = self.app.cluster_secure(password)
        self._admin = self.app.build_admin()
        return os_admin

    def get_admin_credentials(self, context):
        return self.app.get_admin_credentials()

    def store_admin_credentials(self, context, admin_credentials):
        self.app.store_admin_credentials(admin_credentials)
        self._admin = self.app.build_admin()
