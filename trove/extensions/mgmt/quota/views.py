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


class QuotaView(object):

    def __init__(self, quotas):
        self.quotas = quotas

    def data(self):
        rtn = {}
        for resource_name, quota in self.quotas.items():
            rtn[resource_name] = quota.hard_limit
        return {'quotas': rtn}


class QuotaUsageView(object):

    def __init__(self, usages):
        self.usages = usages

    def data(self):
        return {'quotas': [{'resource': resource,
                            'in_use': usage['in_use'],
                            'reserved': usage['reserved'],
                            'limit': usage['limit']
                            } for resource, usage in self.usages.items()]}
