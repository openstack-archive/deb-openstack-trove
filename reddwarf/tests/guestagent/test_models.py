#    Copyright 2012 OpenStack LLC
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
#    under the License

import testtools
from mock import Mock, MagicMock
from reddwarf.guestagent import models
from reddwarf.common import utils
from reddwarf.db import sqlalchemy
from reddwarf.db import models as dbmodels
from proboscis import test

from datetime import datetime


@test(groups=["dbaas.guestagent.dbaas"])
class AgentHeartBeatTest(testtools.TestCase):
    def setUp(self):
        super(AgentHeartBeatTest, self).setUp()

    def tearDown(self):
        super(AgentHeartBeatTest, self).tearDown()

    def test_create(self):
        utils.generate_uuid = Mock()
        sqlalchemy.api.save = MagicMock(
            return_value=dbmodels.DatabaseModelBase)
        dbmodels.DatabaseModelBase.is_valid = Mock(return_value=True)
        models.AgentHeartBeat.create()
        self.assertEqual(1, utils.generate_uuid.call_count)
        self.assertEqual(3,
                         dbmodels.DatabaseModelBase.is_valid.call_count)

    def test_save(self):
        utils.utcnow = Mock()
        dbmodels.DatabaseModelBase = Mock
        dbmodels.get_db_api = MagicMock(
            return_value=dbmodels.DatabaseModelBase)
        sqlalchemy.api.save = Mock()
        dbmodels.DatabaseModelBase.is_valid = Mock(return_value=True)
        self.heartBeat = models.AgentHeartBeat()
        self.heartBeat.save()
        self.assertEqual(1, utils.utcnow.call_count)

    def test_is_active(self):
        models.AGENT_HEARTBEAT = 10000000000
        mock = models.AgentHeartBeat()
        models.AgentHeartBeat.__setitem__(mock, 'updated_at', datetime.now())
        self.assertTrue(models.AgentHeartBeat.is_active(mock))
