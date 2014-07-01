# Copyright 2013 Rackspace Hosting
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
from trove.cmd.common import with_initialize


@with_initialize
def main(conf):
    from trove.common.rpc import service as rpc_service
    from trove.openstack.common import service as openstack_service

    manager = 'trove.conductor.manager.Manager'
    topic = conf.conductor_queue
    server = rpc_service.RpcService(manager=manager, topic=topic)
    launcher = openstack_service.launch(server,
                                        workers=conf.trove_conductor_workers)
    launcher.wait()
