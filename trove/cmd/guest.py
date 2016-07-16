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

import gettext
gettext.install('trove', unicode=1)

import sys

from oslo_config import cfg as openstack_cfg
from oslo_log import log as logging
from oslo_service import service as openstack_service

from trove.common import cfg
from trove.common import debug_utils

CONF = cfg.CONF
# The guest_id opt definition must match the one in common/cfg.py
CONF.register_opts([openstack_cfg.StrOpt('guest_id', default=None,
                                         help="ID of the Guest Instance.")])


def main():
    cfg.parse_args(sys.argv)
    logging.setup(CONF, None)

    debug_utils.setup()

    from trove.guestagent import dbaas
    manager = dbaas.datastore_registry().get(CONF.datastore_manager)
    if not manager:
        msg = ("Manager class not registered for datastore manager %s" %
               CONF.datastore_manager)
        raise RuntimeError(msg)

    # rpc module must be loaded after decision about thread monkeypatching
    # because if thread module is not monkeypatched we can't use eventlet
    # executor from oslo_messaging library.
    from trove import rpc
    rpc.init(CONF)

    from trove.common.rpc import service as rpc_service
    from trove.common.rpc import version as rpc_version
    server = rpc_service.RpcService(
        manager=manager, host=CONF.guest_id,
        rpc_api_version=rpc_version.RPC_API_VERSION)

    launcher = openstack_service.launch(CONF, server)
    launcher.wait()
