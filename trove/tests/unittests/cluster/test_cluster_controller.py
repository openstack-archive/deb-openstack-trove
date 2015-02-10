# Copyright 2014 eBay Software Foundation
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
import jsonschema

from mock import MagicMock
from mock import Mock
from mock import patch
from testtools import TestCase
from testtools.matchers import Is, Equals
from trove.cluster import models
from trove.cluster.models import Cluster
from trove.cluster.service import ClusterController
from trove.cluster import views
import trove.common.cfg as cfg
from trove.common import exception
from trove.common.strategies.cluster import strategy
from trove.common import utils
from trove.datastore import models as datastore_models


class TestClusterController(TestCase):
    def setUp(self):
        super(TestClusterController, self).setUp()
        self.controller = ClusterController()
        self.cluster = {
            "cluster": {
                "name": "products",
                "datastore": {
                    "type": "mongodb",
                    "version": "2.4.10"
                },
                "instances": [
                    {
                        "flavorRef": "7",
                        "volume": {
                            "size": 1
                        },
                    },
                    {
                        "flavorRef": "7",
                        "volume": {
                            "size": 1
                        },
                    },
                    {
                        "flavorRef": "7",
                        "volume": {
                            "size": 1
                        },
                    },
                    {
                        "flavorRef": "7",
                        "volume": {
                            "size": 1
                        },
                    },
                    {
                        "flavorRef": "7",
                        "volume": {
                            "size": 1
                        },
                    }
                ]
            }
        }
        self.add_shard = {
            "add_shard": {}
        }

    def test_get_schema_create(self):
        schema = self.controller.get_schema('create', self.cluster)
        self.assertIsNotNone(schema)
        self.assertTrue('cluster' in schema['properties'])
        self.assertTrue('cluster')

    def test_get_schema_action_add_shard(self):
        schema = self.controller.get_schema('add_shard', self.add_shard)
        self.assertIsNotNone(schema)
        self.assertTrue('add_shard' in schema['properties'])

    def test_validate_create(self):
        body = self.cluster
        schema = self.controller.get_schema('create', body)
        validator = jsonschema.Draft4Validator(schema)
        self.assertTrue(validator.is_valid(body))

    def test_validate_add_shard(self):
        body = self.add_shard
        schema = self.controller.get_schema('add_shard', body)
        validator = jsonschema.Draft4Validator(schema)
        self.assertTrue(validator.is_valid(body))

    def test_validate_create_blankname(self):
        body = self.cluster
        body['cluster']['name'] = "     "
        schema = self.controller.get_schema('create', body)
        validator = jsonschema.Draft4Validator(schema)
        self.assertFalse(validator.is_valid(body))
        errors = sorted(validator.iter_errors(body), key=lambda e: e.path)
        self.assertThat(len(errors), Is(1))
        self.assertThat(errors[0].message,
                        Equals("'     ' does not match '^.*[0-9a-zA-Z]+.*$'"))

    def test_validate_create_blank_datastore(self):
        body = self.cluster
        body['cluster']['datastore']['type'] = ""
        schema = self.controller.get_schema('create', body)
        validator = jsonschema.Draft4Validator(schema)
        self.assertFalse(validator.is_valid(body))
        errors = sorted(validator.iter_errors(body), key=lambda e: e.path)
        error_messages = [error.message for error in errors]
        error_paths = [error.path.pop() for error in errors]
        self.assertThat(len(errors), Is(2))
        self.assertIn("'' is too short", error_messages)
        self.assertIn("'' does not match '^.*[0-9a-zA-Z]+.*$'", error_messages)
        self.assertIn("type", error_paths)

    @patch.object(Cluster, 'create')
    @patch.object(datastore_models, 'get_datastore_version')
    def test_create_clusters_disabled(self,
                                      mock_get_datastore_version,
                                      mock_cluster_create):
        body = self.cluster
        tenant_id = Mock()
        context = Mock()

        req = Mock()
        req.environ = MagicMock()
        req.environ.get = Mock(return_value=context)

        datastore_version = Mock()
        datastore_version.manager = 'mysql'
        mock_get_datastore_version.return_value = (Mock(), datastore_version)

        self.assertRaises(exception.ClusterDatastoreNotSupported,
                          self.controller.create,
                          req,
                          body,
                          tenant_id)

    @patch.object(Cluster, 'create')
    @patch.object(utils, 'get_id_from_href')
    @patch.object(datastore_models, 'get_datastore_version')
    def test_create_clusters(self,
                             mock_get_datastore_version,
                             mock_id_from_href,
                             mock_cluster_create):
        body = self.cluster
        tenant_id = Mock()
        context = Mock()

        req = Mock()
        req.environ = Mock()
        req.environ.__getitem__ = Mock(return_value=context)
        datastore_version = Mock()
        datastore_version.manager = 'mongodb'
        datastore = Mock()
        mock_get_datastore_version.return_value = (datastore,
                                                   datastore_version)
        instances = [{'volume_size': 1, 'flavor_id': '1234'},
                     {'volume_size': 1, 'flavor_id': '1234'},
                     {'volume_size': 1, 'flavor_id': '1234'},
                     {'volume_size': 1, 'flavor_id': '1234'},
                     {'volume_size': 1, 'flavor_id': '1234'}]
        mock_id_from_href.return_value = '1234'

        mock_cluster = Mock()
        mock_cluster.instances = []
        mock_cluster.instances_without_server = []
        mock_cluster.datastore_version.manager = 'mongodb'
        mock_cluster_create.return_value = mock_cluster

        self.controller.create(req, body, tenant_id)
        mock_cluster_create.assert_called_with(context, 'products',
                                               datastore, datastore_version,
                                               instances)

    @patch.object(Cluster, 'load')
    def test_show_cluster(self,
                          mock_cluster_load):
        tenant_id = Mock()
        id = Mock()
        context = Mock()
        req = Mock()
        req.environ = Mock()
        req.environ.__getitem__ = Mock(return_value=context)

        mock_cluster = Mock()
        mock_cluster.instances = []
        mock_cluster.instances_without_server = []
        mock_cluster.datastore_version.manager = 'mongodb'
        mock_cluster_load.return_value = mock_cluster

        self.controller.show(req, tenant_id, id)
        mock_cluster_load.assert_called_with(context, id)

    @patch.object(Cluster, 'load')
    @patch.object(Cluster, 'load_instance')
    def test_show_cluster_instance(self,
                                   mock_cluster_load_instance,
                                   mock_cluster_load):
        tenant_id = Mock()
        cluster_id = Mock()
        instance_id = Mock()
        context = Mock()
        req = Mock()
        req.environ = Mock()
        req.environ.__getitem__ = Mock(return_value=context)
        cluster = Mock()
        mock_cluster_load.return_value = cluster
        cluster.id = cluster_id
        self.controller.show_instance(req, tenant_id, cluster_id, instance_id)
        mock_cluster_load_instance.assert_called_with(context, cluster.id,
                                                      instance_id)

    @patch.object(Cluster, 'load')
    def test_delete_cluster(self, mock_cluster_load):
        tenant_id = Mock()
        cluster_id = Mock()
        req = MagicMock()
        cluster = Mock()
        mock_cluster_load.return_value = cluster
        self.controller.delete(req, tenant_id, cluster_id)
        cluster.delete.assert_called


class TestClusterControllerWithStrategy(TestCase):
    def setUp(self):
        super(TestClusterControllerWithStrategy, self).setUp()
        self.controller = ClusterController()
        self.cluster = {
            "cluster": {
                "name": "products",
                "datastore": {
                    "type": "mongodb",
                    "version": "2.4.10"
                },
                "instances": [
                    {
                        "flavorRef": "7",
                        "volume": {
                            "size": 1
                        },
                    },
                    {
                        "flavorRef": "7",
                        "volume": {
                            "size": 1
                        },
                    },
                    {
                        "flavorRef": "7",
                        "volume": {
                            "size": 1
                        },
                    },
                    {
                        "flavorRef": "7",
                        "volume": {
                            "size": 1
                        },
                    },
                    {
                        "flavorRef": "7",
                        "volume": {
                            "size": 1
                        },
                    }
                ]
            }
        }

    def tearDown(self):
        super(TestClusterControllerWithStrategy, self).tearDown()
        cfg.CONF.clear_override('cluster_support', group='mongodb')
        cfg.CONF.clear_override('api_strategy', group='mongodb')

    @patch.object(datastore_models, 'get_datastore_version')
    @patch.object(models.Cluster, 'create')
    def test_create_clusters_disabled(self,
                                      mock_cluster_create,
                                      mock_get_datastore_version):

        cfg.CONF.set_override('cluster_support', False, group='mongodb')

        body = self.cluster
        tenant_id = Mock()
        context = Mock()

        req = Mock()
        req.environ = MagicMock()
        req.environ.get = Mock(return_value=context)

        datastore_version = Mock()
        datastore_version.manager = 'mongodb'
        mock_get_datastore_version.return_value = (Mock(), datastore_version)

        self.assertRaises(exception.TroveError, self.controller.create, req,
                          body, tenant_id)

    @patch.object(views.ClusterView, 'data', return_value={})
    @patch.object(datastore_models, 'get_datastore_version')
    @patch.object(models.Cluster, 'create')
    def test_create_clusters_enabled(self,
                                     mock_cluster_create,
                                     mock_get_datastore_version,
                                     mock_cluster_view_data):

        cfg.CONF.set_override('cluster_support', True, group='mongodb')

        body = self.cluster
        tenant_id = Mock()
        context = Mock()

        req = Mock()
        req.environ = MagicMock()
        req.environ.get = Mock(return_value=context)

        datastore_version = Mock()
        datastore_version.manager = 'mongodb'
        mock_get_datastore_version.return_value = (Mock(), datastore_version)

        mock_cluster = Mock()
        mock_cluster.datastore_version.manager = 'mongodb'
        mock_cluster_create.return_value = mock_cluster
        self.controller.create(req, body, tenant_id)

    @patch.object(models.Cluster, 'load')
    def test_controller_action_no_strategy(self,
                                           mock_cluster_load):

        body = {'do_stuff2': {}}
        tenant_id = Mock()
        context = Mock()
        id = Mock()

        req = Mock()
        req.environ = MagicMock()
        req.environ.get = Mock(return_value=context)

        cluster = Mock()
        cluster.datastore_version.manager = 'mongodb'
        mock_cluster_load.return_value = cluster

        self.assertRaises(exception.TroveError, self.controller.action, req,
                          body, tenant_id, id)

    @patch.object(strategy, 'load_api_strategy')
    @patch.object(models.Cluster, 'load')
    def test_controller_action_found(self,
                                     mock_cluster_load,
                                     mock_cluster_api_strategy):

        body = {'do_stuff': {}}
        tenant_id = Mock()
        context = Mock()
        id = Mock()

        req = Mock()
        req.environ = MagicMock()
        req.environ.get = Mock(return_value=context)

        cluster = Mock()
        cluster.datastore_version.manager = 'mongodb'
        mock_cluster_load.return_value = cluster

        strat = Mock()
        do_stuff_func = Mock()
        strat.cluster_controller_actions = \
            {'do_stuff': do_stuff_func}
        mock_cluster_api_strategy.return_value = strat

        self.controller.action(req, body, tenant_id, id)
        self.assertEqual(1, do_stuff_func.call_count)
