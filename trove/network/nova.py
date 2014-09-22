# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

from trove.common import exception
from trove.common import remote
from trove.network import base
from trove.openstack.common import log as logging
from novaclient import exceptions as nova_exceptions


LOG = logging.getLogger(__name__)


class NovaNetwork(base.NetworkDriver):

    def __init__(self, context):
        try:
            self.client = remote.create_nova_client(
                context)
        except nova_exceptions.ClientException as e:
            raise exception.TroveError(str(e))

    def get_sec_group_by_id(self, group_id):
        try:
            return self.client.security_groups.get(group_id)
        except nova_exceptions.ClientException as e:
            LOG.exception('Failed to get remote security group')
            raise exception.TroveError(str(e))

    def create_security_group(self, name, description):
        try:
            sec_group = self.client.security_groups.create(
                name=name, description=description)
            return sec_group
        except nova_exceptions.ClientException as e:
            LOG.exception('Failed to create remote security group')
            raise exception.SecurityGroupCreationError(str(e))

    def delete_security_group(self, sec_group_id):
        try:
            self.client.security_groups.delete(sec_group_id)
        except nova_exceptions.ClientException as e:
            LOG.exception('Failed to delete remote security group')
            raise exception.SecurityGroupDeletionError(str(e))

    def add_security_group_rule(self, sec_group_id, protocol,
                                from_port, to_port, cidr):
        try:
            sec_group_rule = self.client.security_group_rules.create(
                parent_group_id=sec_group_id,
                ip_protocol=protocol,
                from_port=from_port,
                to_port=to_port,
                cidr=cidr)

            return sec_group_rule
        except nova_exceptions.ClientException as e:
            LOG.exception('Failed to add rule to remote security group')
            raise exception.SecurityGroupRuleCreationError(str(e))

    def delete_security_group_rule(self, sec_group_rule_id):
        try:
            self.client.security_group_rules.delete(sec_group_rule_id)

        except nova_exceptions.ClientException as e:
            LOG.exception('Failed to delete rule to remote security group')
            raise exception.SecurityGroupRuleDeletionError(str(e))
