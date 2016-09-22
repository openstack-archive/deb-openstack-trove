# Copyright 2010-2012 OpenStack Foundation
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

"""Model classes that form the core of instance flavor functionality."""


from novaclient import exceptions as nova_exceptions
from trove.common import exception
from trove.common.models import NovaRemoteModelBase
from trove.common.remote import create_nova_client


class Flavor(object):

    _data_fields = ['id', 'links', 'name', 'ram', 'vcpus', 'disk', 'ephemeral']

    def __init__(self, flavor=None, context=None, flavor_id=None):
        if flavor:
            self.flavor = flavor
            return
        if flavor_id and context:
            try:
                client = create_nova_client(context)
                self.flavor = client.flavors.get(flavor_id)
            except nova_exceptions.NotFound as e:
                raise exception.NotFound(uuid=flavor_id)
            except nova_exceptions.ClientException as e:
                raise exception.TroveError(str(e))
            return
        msg = ("Flavor is not defined, and"
               " context and flavor_id were not specified.")
        raise exception.InvalidModelError(errors=msg)

    @property
    def id(self):
        return self.flavor.id

    @property
    def name(self):
        return self.flavor.name

    @property
    def ram(self):
        return self.flavor.ram

    @property
    def vcpus(self):
        return self.flavor.vcpus

    @property
    def links(self):
        return self.flavor.links

    @property
    def disk(self):
        return self.flavor.disk

    @property
    def ephemeral(self):
        return self.flavor.ephemeral


class Flavors(NovaRemoteModelBase):

    def __init__(self, context):
        nova_flavors = create_nova_client(context).flavors.list()
        self.flavors = [Flavor(flavor=item) for item in nova_flavors]

    def __iter__(self):
        for item in self.flavors:
            yield item
