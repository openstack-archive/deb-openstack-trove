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

from eventlet.timeout import Timeout
from oslo_log import log as logging

from trove.common import cfg
from trove.common.i18n import _
from trove.common.remote import create_nova_client
from trove.common.strategies.cluster import base
from trove.common.template import ClusterConfigTemplate
from trove.common import utils
from trove.instance.models import DBInstance
from trove.instance.models import Instance
from trove.taskmanager import api as task_api
import trove.taskmanager.models as task_models


LOG = logging.getLogger(__name__)
CONF = cfg.CONF
USAGE_SLEEP_TIME = CONF.usage_sleep_time  # seconds.


class PXCTaskManagerStrategy(base.BaseTaskManagerStrategy):

    @property
    def task_manager_api_class(self):
        return task_api.API

    @property
    def task_manager_cluster_tasks_class(self):
        return PXCClusterTasks


class PXCClusterTasks(task_models.ClusterTasks):

    CLUSTER_REPLICATION_USER = "clusterrepuser"

    def _render_cluster_config(self, context, instance, cluster_ips,
                               cluster_name, replication_user):
        client = create_nova_client(context)
        flavor = client.flavors.get(instance.flavor_id)
        instance_ip = self.get_ip(instance)
        config = ClusterConfigTemplate(
            self.datastore_version, flavor, instance.id)
        replication_user_pass = "%(name)s:%(password)s" % replication_user
        config_rendered = config.render(
            replication_user_pass=replication_user_pass,
            cluster_ips=cluster_ips,
            cluster_name=cluster_name,
            instance_ip=instance_ip,
            instance_name=instance.name,
        )
        return config_rendered

    def create_cluster(self, context, cluster_id):
        LOG.debug("Begin create_cluster for id: %s." % cluster_id)

        def _create_cluster():
            # Fetch instances by cluster_id against instances table.
            db_instances = DBInstance.find_all(cluster_id=cluster_id).all()
            instance_ids = [db_instance.id for db_instance in db_instances]

            LOG.debug("Waiting for instances to get to cluster-ready status.")
            # Wait for cluster members to get to cluster-ready status.
            if not self._all_instances_ready(instance_ids, cluster_id):
                return

            LOG.debug("All members ready, proceeding for cluster setup.")
            instances = [Instance.load(context, instance_id) for instance_id
                         in instance_ids]

            cluster_ips = [self.get_ip(instance) for instance in instances]
            instance_guests = [self.get_guest(instance)
                               for instance in instances]

            # Create replication user and password for synchronizing the
            # PXC cluster
            replication_user = {
                "name": self.CLUSTER_REPLICATION_USER,
                "password": utils.generate_random_password(),
            }

            # PXC cluster name must be unique and be shorter than a full
            # uuid string so we remove the hyphens and chop it off. It was
            # recommended to be 16 chars or less.
            # (this is not currently documented on PXC docs)
            cluster_name = utils.generate_uuid().replace("-", "")[:16]

            LOG.debug("Configuring cluster configuration.")
            try:
                # Set the admin password for all the instances because the
                # password in the my.cnf will be wrong after the joiner
                # instances syncs with the donor instance.
                admin_password = str(utils.generate_random_password())
                for guest in instance_guests:
                    guest.reset_admin_password(admin_password)

                bootstrap = True
                for instance in instances:
                    guest = self.get_guest(instance)

                    # render the conf.d/cluster.cnf configuration
                    cluster_configuration = self._render_cluster_config(
                        context,
                        instance, ",".join(cluster_ips),
                        cluster_name,
                        replication_user)

                    # push the cluster config and bootstrap the first instance
                    guest.install_cluster(replication_user,
                                          cluster_configuration,
                                          bootstrap)
                    bootstrap = False

                LOG.debug("Finalizing cluster configuration.")
                for guest in instance_guests:
                    guest.cluster_complete()
            except Exception:
                LOG.exception(_("Error creating cluster."))
                self.update_statuses_on_failure(cluster_id)

        timeout = Timeout(CONF.cluster_usage_timeout)
        try:
            _create_cluster()
            self.reset_task()
        except Timeout as t:
            if t is not timeout:
                raise  # not my timeout
            LOG.exception(_("Timeout for building cluster."))
            self.update_statuses_on_failure(cluster_id)
        finally:
            timeout.cancel()

        LOG.debug("End create_cluster for id: %s." % cluster_id)
