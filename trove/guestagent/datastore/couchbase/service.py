# Copyright (c) 2013 eBay Software Foundation
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

import json

from trove.common import cfg
from trove.common import exception
from trove.common import instance as rd_instance
from trove.common import utils as utils
from trove.guestagent import pkg
from trove.guestagent.common import operating_system
from trove.guestagent.datastore import service
from trove.guestagent.datastore.couchbase import system
from trove.openstack.common import log as logging
from trove.openstack.common.gettextutils import _

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
packager = pkg.Package()


class CouchbaseApp(object):
    """
    Handles installation and configuration of couchbase
    on a trove instance.
    """
    def __init__(self, status, state_change_wait_time=None):
        """
        Sets default status and state_change_wait_time
        """
        if state_change_wait_time:
            self.state_change_wait_time = state_change_wait_time
        else:
            self.state_change_wait_time = CONF.state_change_wait_time
        self.status = status

    def install_if_needed(self, packages):
        """
        Install couchbase if needed, do nothing if it is already installed.
        """
        LOG.info(_('Preparing Guest as Couchbase Server'))
        if not packager.pkg_is_installed(packages):
            LOG.info(_('Installing Couchbase'))
            self._install_couchbase(packages)
        self.initial_setup()

    def initial_setup(self):
        self.ip_address = operating_system.get_ip_address()
        mount_point = CONF.get('couchbase').mount_point
        try:
            LOG.info(_('Couchbase Server change data dir path'))
            utils.execute_with_timeout(system.cmd_own_data_dir, shell=True)
            utils.execute_with_timeout(
                (system.cmd_node_init
                 % {'data_path': mount_point,
                    'IP': self.ip_address}), shell=True)
            utils.execute_with_timeout(
                system.cmd_rm_old_data_dir, shell=True)
            LOG.info(_('Couchbase Server initialize cluster'))
            utils.execute_with_timeout(
                (system.cmd_cluster_init % {'IP': self.ip_address}),
                shell=True)
            utils.execute_with_timeout(system.cmd_set_swappiness, shell=True)
            utils.execute_with_timeout(system.cmd_update_sysctl_conf,
                                       shell=True)
            LOG.info(_('Couchbase Server initial setup finished'))
        except exception.ProcessExecutionError as e:
            LOG.error(_('Process execution error %s') % e)
            raise RuntimeError("Couchbase Server initial setup failed")

    def complete_install_or_restart(self):
        """
        finalize status updates for install or restart.
        """
        self.status.end_install_or_restart()

    def _install_couchbase(self, packages):
        """
        Install the Couchbase Server.
        """
        LOG.debug(_('Installing Couchbase Server'))
        msg = _("Creating %s") % system.COUCHBASE_CONF_DIR
        LOG.debug(msg)
        utils.execute_with_timeout('mkdir',
                                   '-p',
                                   system.COUCHBASE_CONF_DIR,
                                   run_as_root=True,
                                   root_helper='sudo')
        pkg_opts = {}
        packager.pkg_install(packages, pkg_opts, system.TIME_OUT)
        self.start_db()
        LOG.debug(_('Finished installing Couchbase Server'))

    def _enable_db_on_boot(self):
        """
        Enables Couchbase Server on boot.
        """
        LOG.info(_('Enabling Couchbase Server on boot.'))
        try:
            couchbase_service = operating_system.service_discovery(
                system.SERVICE_CANDIDATES)
            utils.execute_with_timeout(
                couchbase_service['cmd_enable'], shell=True)
        except KeyError:
            raise RuntimeError(_(
                "Command to enable Couchbase Server on boot not found."))

    def _disable_db_on_boot(self):
        LOG.info(_("Disabling Couchbase Server on boot"))
        try:
            couchbase_service = operating_system.service_discovery(
                system.SERVICE_CANDIDATES)
            utils.execute_with_timeout(
                couchbase_service['cmd_disable'], shell=True)
        except KeyError:
            raise RuntimeError(
                "Command to disable Couchbase Server on boot not found.")

    def stop_db(self, update_db=False, do_not_start_on_reboot=False):
        """
        Stops Couchbase Server on the trove instance.
        """
        LOG.info(_('Stopping Couchbase Server...'))
        if do_not_start_on_reboot:
            self._disable_db_on_boot()

        try:
            couchbase_service = operating_system.service_discovery(
                system.SERVICE_CANDIDATES)
            utils.execute_with_timeout(
                couchbase_service['cmd_stop'], shell=True)
        except KeyError:
            raise RuntimeError("Command to stop Couchbase Server not found")

        if not self.status.wait_for_real_status_to_change_to(
                rd_instance.ServiceStatuses.SHUTDOWN,
                self.state_change_wait_time, update_db):
            LOG.error(_('Could not stop Couchbase Server!'))
            self.status.end_install_or_restart()
            raise RuntimeError(_("Could not stop Couchbase Server"))

    def restart(self):
        LOG.info(_("Restarting Couchbase Server"))
        try:
            self.status.begin_restart()
            self.stop_db()
            self.start_db()
        finally:
            self.status.end_install_or_restart()

    def start_db(self, update_db=False):
        """
        Start the Couchbase Server.
        """
        LOG.info(_("Starting Couchbase Server..."))

        self._enable_db_on_boot()
        try:
            couchbase_service = operating_system.service_discovery(
                system.SERVICE_CANDIDATES)
            utils.execute_with_timeout(
                couchbase_service['cmd_start'], shell=True)
        except exception.ProcessExecutionError:
            pass
        except KeyError:
            raise RuntimeError("Command to start Couchbase Server not found.")

        if not self.status.wait_for_real_status_to_change_to(
                rd_instance.ServiceStatuses.RUNNING,
                self.state_change_wait_time, update_db):
            LOG.error(_("Start up of Couchbase Server failed!"))
            try:
                utils.execute_with_timeout(system.cmd_kill)
            except exception.ProcessExecutionError as p:
                LOG.error('Error killing stalled Couchbase start command.')
                LOG.error(p)
            self.status.end_install_or_restart()
            raise RuntimeError("Could not start Couchbase Server")


class CouchbaseAppStatus(service.BaseDbStatus):
    """
    Handles all of the status updating for the couchbase guest agent.
    """
    def _get_actual_db_status(self):
        self.ip_address = operating_system.get_ip_address()
        try:
            out, err = utils.execute_with_timeout(
                (system.cmd_couchbase_status %
                 {'IP': self.ip_address}),
                shell=True)
            server_stats = json.loads(out)
            if not err and server_stats["clusterMembership"] == "active":
                return rd_instance.ServiceStatuses.RUNNING
            else:
                return rd_instance.ServiceStatuses.SHUTDOWN
        except exception.ProcessExecutionError as e:
            LOG.error(_("Process execution %s ") % e)
            return rd_instance.ServiceStatuses.SHUTDOWN
