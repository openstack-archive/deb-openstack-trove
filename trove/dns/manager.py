# Copyright (c) 2011 OpenStack Foundation
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

"""
Dns manager.
"""

from oslo_log import log as logging

from trove.common import cfg
from trove.common import utils

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class DnsManager(object):
    """Handles associating DNS to and from IPs."""

    def __init__(self, dns_driver=None, dns_instance_entry_factory=None,
                 *args, **kwargs):
        if not dns_driver:
            dns_driver = CONF.dns_driver
        dns_driver = utils.import_class(dns_driver)
        self.driver = dns_driver()

        if not dns_instance_entry_factory:
            dns_instance_entry_factory = CONF.dns_instance_entry_factory
        entry_factory = utils.import_class(dns_instance_entry_factory)
        self.entry_factory = entry_factory()

    def create_instance_entry(self, instance_id, content):
        """Connects a new instance with a DNS entry.

        :param instance_id: The trove instance_id to associate.
        :param content: The IP content attached to the instance.

        """
        entry = self.entry_factory.create_entry(instance_id)
        if entry:
            LOG.debug("Creating entry address %s." % str(entry))
            self.driver.create_entry(entry, content)
        else:
            LOG.debug("Entry address not found for instance %s" % instance_id)

    def delete_instance_entry(self, instance_id, content=None):
        """Removes a DNS entry associated to an instance.

        :param instance_id: The trove instance id to associate.
        :param content: The IP content attached to the instance.

        """
        entry = self.entry_factory.create_entry(instance_id)
        LOG.debug("Deleting instance entry with %s" % str(entry))
        if entry:
            self.driver.delete_entry(entry.name, entry.type)

    def determine_hostname(self, instance_id):
        """
        Create the hostname field based on the instance id.
        Use instance by default.
        """
        entry = self.entry_factory.create_entry(instance_id)
        if entry:
            return entry.name
        else:
            return None
