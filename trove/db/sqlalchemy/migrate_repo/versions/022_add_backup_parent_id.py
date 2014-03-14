# Copyright 2013 OpenStack Foundation
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

from sqlalchemy.schema import Column
from sqlalchemy.schema import MetaData

from trove.db.sqlalchemy.migrate_repo.schema import String
from trove.db.sqlalchemy.migrate_repo.schema import Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # add column:
    backups = Table('backups', meta, autoload=True)
    backups.create_column(Column('parent_id', String(36), nullable=True))


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # drop column:
    backups = Table('backups', meta, autoload=True)
    backups.drop_column('parent_id')
