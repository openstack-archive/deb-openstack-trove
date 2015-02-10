# Copyright 2013 OpenStack Foundation
# Copyright 2013 Rackspace Hosting
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

import inspect
import os
from oslo import messaging
from oslo.utils import importutils
from trove.openstack.common.gettextutils import _
from trove.openstack.common import log as logging
from trove.openstack.common import loopingcall
from trove.openstack.common import service

from trove.common import cfg
from trove import rpc

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class RpcService(service.Service):

    def __init__(self, host=None, binary=None, topic=None, manager=None,
                 rpc_api_version=None):
        super(RpcService, self).__init__()
        self.host = host or CONF.host
        self.binary = binary or os.path.basename(inspect.stack()[-1][1])
        self.topic = topic or self.binary.rpartition('trove-')[2]
        self.manager_impl = importutils.import_object(manager)
        self.report_interval = CONF.report_interval
        self.rpc_api_version = rpc_api_version or \
            self.manager_impl.RPC_API_VERSION

    def start(self):
        LOG.debug("Creating RPC server for service %s", self.topic)

        target = messaging.Target(topic=self.topic, server=self.host,
                                  version=self.rpc_api_version)

        if not hasattr(self.manager_impl, 'target'):
            self.manager_impl.target = target

        endpoints = [self.manager_impl]
        self.rpcserver = rpc.get_server(target, endpoints)
        self.rpcserver.start()

        # TODO(hub-cap): Currently the context is none... do we _need_ it here?
        if self.report_interval > 0:
            pulse = loopingcall.FixedIntervalLoopingCall(
                self.manager_impl.run_periodic_tasks, context=None)
            pulse.start(interval=self.report_interval,
                        initial_delay=self.report_interval)
            pulse.wait()

    def stop(self):
        # Try to shut the connection down, but if we get any sort of
        # errors, go ahead and ignore them.. as we're shutting down anyway
        try:
            self.rpcserver.stop()
        except Exception:
            LOG.info(_("Failed to stop RPC server before shutdown. "))
            pass

        super(RpcService, self).stop()
