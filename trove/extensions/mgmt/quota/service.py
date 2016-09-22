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

from oslo_log import log as logging

from trove.common.auth import admin_context
from trove.common import exception
from trove.common.i18n import _
from trove.common import wsgi
from trove.extensions.mgmt.quota import views
from trove.quota.models import Quota
from trove.quota.quota import QUOTAS as quota_engine

LOG = logging.getLogger(__name__)


class QuotaController(wsgi.Controller):
    """Controller for quota functionality."""

    @admin_context
    def show(self, req, tenant_id, id):
        """Return all quotas for this tenant."""
        LOG.info(_("Indexing quota info for tenant '%(id)s'\n"
                   "req : '%(req)s'\n\n") % {
                       "id": id, "req": req})

        usages = quota_engine.get_all_quota_usages_by_tenant(id)
        limits = quota_engine.get_all_quotas_by_tenant(id)
        map(lambda r: setattr(usages[r], "limit", limits[r].hard_limit),
            usages.keys())
        return wsgi.Result(views.QuotaUsageView(usages).data(), 200)

    @admin_context
    def update(self, req, body, tenant_id, id):
        LOG.info(_("Updating quota limits for tenant '%(id)s'\n"
                   "req : '%(req)s'\n\n") % {
                       "id": id, "req": req})

        if not body:
            raise exception.BadRequest(_("Invalid request body."))

        quotas = {}
        quota = None
        registered_resources = quota_engine.resources
        for resource, limit in body['quotas'].items():
            if limit is None:
                continue
            if resource == "xmlns":
                continue
            if resource not in registered_resources:
                raise exception.QuotaResourceUnknown(unknown=resource)
            try:
                quota = Quota.find_by(tenant_id=id, resource=resource)
                quota.hard_limit = limit
                quota.save()
            except exception.ModelNotFoundError:
                quota = Quota.create(tenant_id=id,
                                     resource=resource,
                                     hard_limit=limit)

            quotas[resource] = quota

        return wsgi.Result(views.QuotaView(quotas).data(), 200)
