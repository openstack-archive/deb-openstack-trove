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

from novaclient import exceptions as nova_exceptions
from oslo_log import log as logging

from trove.cluster import models
from trove.cluster.models import Cluster
from trove.cluster.tasks import ClusterTasks
from trove.cluster.views import ClusterView
from trove.common import cfg
from trove.common import exception
from trove.common.exception import TroveError
from trove.common.i18n import _
from trove.common import remote
from trove.common.strategies.cluster import base
from trove.extensions.mgmt.clusters.views import MgmtClusterView
from trove.instance import models as inst_models
from trove.quota.quota import check_quotas
from trove.taskmanager import api as task_api
LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class RedisAPIStrategy(base.BaseAPIStrategy):

    @property
    def cluster_class(self):
        return RedisCluster

    @property
    def cluster_view_class(self):
        return RedisClusterView

    @property
    def mgmt_cluster_view_class(self):
        return RedisMgmtClusterView


class RedisCluster(models.Cluster):

    @staticmethod
    def _create_instances(context, db_info, datastore, datastore_version,
                          instances):
        Redis_conf = CONF.get(datastore_version.manager)
        num_instances = len(instances)
        total_volume_allocation = 0

        # Validate and Cache flavors
        nova_client = remote.create_nova_client(context)
        unique_flavors = set(map(lambda i: i['flavor_id'], instances))
        flavor_cache = {}
        for fid in unique_flavors:
            try:
                flavor_cache.update({fid: nova_client.flavors.get(fid)})
            except nova_exceptions.NotFound:
                raise exception.FlavorNotFound(uuid=fid)

        # Checking volumes
        name_index = 1
        for instance in instances:
            if not instance.get('name'):
                instance['name'] = "%s-member-%s" % (db_info.name, name_index)
                name_index += 1
            volume_size = instance.get('volume_size')
            if Redis_conf.volume_support:
                models.validate_volume_size(volume_size)
                total_volume_allocation += volume_size
            else:
                if volume_size:
                    raise exception.VolumeNotSupported()
                ephemeral_support = Redis_conf.device_path
                flavor_id = instance['flavor_id']
                flavor = flavor_cache[flavor_id]
                if ephemeral_support and flavor.ephemeral == 0:
                    raise exception.LocalStorageNotSpecified(flavor=flavor_id)

        # Check quotas
        quota_request = {'instances': num_instances,
                         'volumes': total_volume_allocation}
        check_quotas(context.tenant, quota_request)

        # Creating member instances
        return map(lambda instance:
                   inst_models.Instance.create(context,
                                               instance['name'],
                                               instance['flavor_id'],
                                               datastore_version.image_id,
                                               [], [],
                                               datastore, datastore_version,
                                               instance.get('volume_size'),
                                               None,
                                               instance.get(
                                                   'availability_zone', None),
                                               instance.get('nics', None),
                                               configuration_id=None,
                                               cluster_config={
                                                   "id": db_info.id,
                                                   "instance_type": "member"}
                                               ),
                   instances)

    @classmethod
    def create(cls, context, name, datastore, datastore_version,
               instances, extended_properties):
        LOG.debug("Initiating cluster creation.")

        # Updating Cluster Task

        db_info = models.DBCluster.create(
            name=name, tenant_id=context.tenant,
            datastore_version_id=datastore_version.id,
            task_status=ClusterTasks.BUILDING_INITIAL)

        cls._create_instances(context, db_info, datastore, datastore_version,
                              instances)

        # Calling taskmanager to further proceed for cluster-configuration
        task_api.load(context, datastore_version.manager).create_cluster(
            db_info.id)

        return RedisCluster(context, db_info, datastore, datastore_version)

    def grow(self, instances):
        LOG.debug("Growing cluster.")

        self.validate_cluster_available()

        context = self.context
        db_info = self.db_info
        datastore = self.ds
        datastore_version = self.ds_version

        db_info.update(task_status=ClusterTasks.GROWING_CLUSTER)

        new_instances = self._create_instances(context, db_info,
                                               datastore, datastore_version,
                                               instances)

        task_api.load(context, datastore_version.manager).grow_cluster(
            db_info.id, [instance.id for instance in new_instances])

        return RedisCluster(context, db_info, datastore, datastore_version)

    def shrink(self, removal_ids):
        LOG.debug("Shrinking cluster %s.", self.id)

        self.validate_cluster_available()

        cluster_info = self.db_info
        cluster_info.update(task_status=ClusterTasks.SHRINKING_CLUSTER)
        try:
            removal_insts = [inst_models.Instance.load(self.context, inst_id)
                             for inst_id in removal_ids]
            node_ids = [Cluster.get_guest(instance).get_node_id_for_removal()
                        for instance in removal_insts]
            if None in node_ids:
                raise TroveError(_("Some nodes cannot be removed (check slots)"
                                   ))

            all_instances = (
                inst_models.DBInstance.find_all(cluster_id=self.id,
                                                deleted=False).all())
            remain_insts = [inst_models.Instance.load(self.context, inst.id)
                            for inst in all_instances
                            if inst.id not in removal_ids]
            map(lambda x: Cluster.get_guest(x).remove_nodes(node_ids),
                remain_insts)
            map(lambda x: x.update_db(cluster_id=None), removal_insts)
            map(inst_models.Instance.delete, removal_insts)

            return RedisCluster(self.context, cluster_info,
                                self.ds, self.ds_version)
        finally:
            cluster_info.update(task_status=ClusterTasks.NONE)


class RedisClusterView(ClusterView):

    def build_instances(self):
        return self._build_instances(['member'], ['member'])


class RedisMgmtClusterView(MgmtClusterView):

    def build_instances(self):
        return self._build_instances(['member'], ['member'])
