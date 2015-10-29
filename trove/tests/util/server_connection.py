# Copyright 2013 OpenStack Foundation
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

from trove import tests
from trove.tests import util
from trove.tests.util.users import Requirements


def create_server_connection(instance_id):
    if util.test_config.use_local_ovz:
        return OpenVZServerConnection(instance_id)
    return ServerSSHConnection(instance_id)


class ServerSSHConnection(object):
    def __init__(self, instance_id):
        self.instance_id = instance_id
        req_admin = Requirements(is_admin=True)
        self.user = util.test_config.users.find_user(req_admin)
        self.dbaas_admin = util.create_dbaas_client(self.user)
        self.instance = self.dbaas_admin.management.show(self.instance_id)
        self.ip_address = self.instance.ip[0]
        TROVE_TEST_SSH_USER = os.environ.get('TROVE_TEST_SSH_USER')
        if TROVE_TEST_SSH_USER and '@' not in self.ip_address:
            self.ip_address = TROVE_TEST_SSH_USER + '@' + self.ip_address

    def execute(self, cmd):
        exe_cmd = "%s %s %s" % (tests.SSH_CMD, self.ip_address, cmd)
        print("RUNNING COMMAND: %s" % exe_cmd)
        return util.process(exe_cmd)


class OpenVZServerConnection(object):
    def __init__(self, instance_id):
        self.instance_id = instance_id
        req_admin = Requirements(is_admin=True)
        self.user = util.test_config.users.find_user(req_admin)
        self.dbaas_admin = util.create_dbaas_client(self.user)
        self.instance = self.dbaas_admin.management.show(self.instance_id)
        self.instance_local_id = self.instance.server["local_id"]

    def execute(self, cmd):
        exe_cmd = "sudo vzctl exec %s %s" % (self.instance_local_id, cmd)
        print("RUNNING COMMAND: %s" % exe_cmd)
        return util.process(exe_cmd)
