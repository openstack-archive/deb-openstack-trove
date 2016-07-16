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

import re

from oslo_log import log as logging
from oslo_utils import strutils
import webob.exc

from trove.common import exception
from trove.common.i18n import _
from trove.common import wsgi

LOG = logging.getLogger(__name__)


class AuthorizationMiddleware(wsgi.Middleware):

    def __init__(self, application, auth_providers, **local_config):
        self.auth_providers = auth_providers
        LOG.debug("Auth middleware providers: %s" % auth_providers)
        super(AuthorizationMiddleware, self).__init__(application,
                                                      **local_config)

    def process_request(self, request):
        roles = request.headers.get('X_ROLE', '').split(',')
        LOG.debug("Processing auth request with roles: %s" % roles)
        tenant_id = request.headers.get('X-Tenant-Id', None)
        LOG.debug("Processing auth request with tenant_id: %s" % tenant_id)
        for provider in self.auth_providers:
            provider.authorize(request, tenant_id, roles)

    @classmethod
    def factory(cls, global_config, **local_config):
        def _factory(app):
            LOG.debug("Created auth middleware with config: %s" %
                      local_config)
            return cls(app, [TenantBasedAuth()], **local_config)
        return _factory


class TenantBasedAuth(object):

    # The paths differ from melange, so the regex must differ as well,
    # trove starts with a tenant_id
    tenant_scoped_url = re.compile("/(?P<tenant_id>.*?)/.*")

    def authorize(self, request, tenant_id, roles):
        match_for_tenant = self.tenant_scoped_url.match(request.path_info)
        if (match_for_tenant and
                tenant_id == match_for_tenant.group('tenant_id')):
            LOG.debug(strutils.mask_password(
                      _("Authorized tenant '%(tenant_id)s' request: "
                        "%(request)s") %
                      {'tenant_id': tenant_id, 'request': request}))
            return True

        msg = _(
            "User with tenant id %s cannot access this resource.") % tenant_id

        LOG.error(msg)
        raise webob.exc.HTTPForbidden(msg)


def admin_context(f):
    """
    Verify that the current context has administrative access,
    or throw an exception. Trove API functions typically take the form
    function(self, req), or function(self, req, id).
    """
    def wrapper(*args, **kwargs):
        try:
            req = args[1]
            context = req.environ.get('trove.context')
        except Exception:
            raise exception.TroveError("Cannot load request context.")
        if not context.is_admin:
            raise exception.Forbidden("User does not have admin privileges.")
        return f(*args, **kwargs)
    return wrapper
