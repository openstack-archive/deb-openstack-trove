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
import trove.common.wsgi as wsgi
import webob

import testtools
from testtools.matchers import Equals, Is, Not


class TestWsgi(testtools.TestCase):
    def test_process_request(self):
        middleware = wsgi.ContextMiddleware("test_trove")
        req = webob.BaseRequest({})
        token = 'MI23fdf2defg123'
        user_id = 'test_user_id'
        req.headers = {
            'X-User': 'do not use - deprecated',
            'X-User-ID': user_id,
            'X-Auth-Token': token,
            'X-Service-Catalog': '[]'
        }
        req.environ = {}
        # invocation
        middleware.process_request(req)
        # assertions
        ctx = req.environ[wsgi.CONTEXT_KEY]
        self.assertThat(ctx, Not(Is(None)))
        self.assertThat(ctx.user, Equals(user_id))
        self.assertThat(ctx.auth_token, Equals(token))
        self.assertEqual(0, len(ctx.service_catalog))
