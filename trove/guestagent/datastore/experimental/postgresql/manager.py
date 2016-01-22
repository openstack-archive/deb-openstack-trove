# Copyright (c) 2013 OpenStack Foundation
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

from oslo_log import log as logging

from .service.config import PgSqlConfig
from .service.database import PgSqlDatabase
from .service.install import PgSqlInstall
from .service.root import PgSqlRoot
from .service.status import PgSqlAppStatus
import pgutil
from trove.common import utils
from trove.guestagent import backup
from trove.guestagent.datastore import manager
from trove.guestagent import volume


LOG = logging.getLogger(__name__)


class Manager(
        PgSqlDatabase,
        PgSqlRoot,
        PgSqlConfig,
        PgSqlInstall,
        manager.Manager
):

    PG_BUILTIN_ADMIN = 'postgres'

    def __init__(self):
        super(Manager, self).__init__('postgresql')

    @property
    def status(self):
        return PgSqlAppStatus.get()

    @property
    def configuration_manager(self):
        return self._configuration_manager

    def do_prepare(self, context, packages, databases, memory_mb, users,
                   device_path, mount_point, backup_info, config_contents,
                   root_password, overrides, cluster_config, snapshot):
        pgutil.PG_ADMIN = self.PG_BUILTIN_ADMIN
        self.install(context, packages)
        self.stop_db(context)
        if device_path:
            device = volume.VolumeDevice(device_path)
            device.format()
            if os.path.exists(mount_point):
                device.migrate_data(mount_point)
            device.mount(mount_point)
        self.configuration_manager.save_configuration(config_contents)
        self.apply_initial_guestagent_configuration()
        self.start_db(context)

        if backup_info:
            backup.restore(context, backup_info, '/tmp')
            pgutil.PG_ADMIN = self.ADMIN_USER
        else:
            self._secure(context)

        if root_password and not backup_info:
            self.enable_root(context, root_password)

    def _secure(self, context):
        # Create a new administrative user for Trove and also
        # disable the built-in superuser.
        self.create_database(context, [{'_name': self.ADMIN_USER}])
        self._create_admin_user(context)
        pgutil.PG_ADMIN = self.ADMIN_USER
        postgres = {'_name': self.PG_BUILTIN_ADMIN,
                    '_password': utils.generate_random_password()}
        self.alter_user(context, postgres, 'NOSUPERUSER', 'NOLOGIN')

    def create_backup(self, context, backup_info):
        backup.backup(context, backup_info)
