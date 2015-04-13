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

from trove.openstack.common import log as logging
import os

from migrate.versioning import api as versioning_api
# See LP bug #719834. sqlalchemy-migrate changed location of
# exceptions.py after 0.6.0.
try:
    from migrate.versioning import exceptions as versioning_exceptions
except ImportError:
    from migrate import exceptions as versioning_exceptions

from trove.common import exception


logger = logging.getLogger('trove.db.sqlalchemy.migration')


def db_version(options, repo_path=None):
    """Return the database's current migration number.

    :param options: options dict
    :retval version number

    """
    repo_path = get_migrate_repo_path(repo_path)
    sql_connection = options['database']['connection']
    try:
        return versioning_api.db_version(sql_connection, repo_path)
    except versioning_exceptions.DatabaseNotControlledError:
        msg = ("database '%(sql_connection)s' is not under migration control"
               % {'sql_connection': sql_connection})
        raise exception.DatabaseMigrationError(msg)


def upgrade(options, version=None, repo_path=None):
    """Upgrade the database's current migration level.

    :param options: options dict
    :param version: version to upgrade (defaults to latest)
    :retval version number

    """
    db_version(options, repo_path)  # Ensure db is under migration control
    repo_path = get_migrate_repo_path(repo_path)
    sql_connection = options['database']['connection']
    version_str = version or 'latest'
    logger.info("Upgrading %(sql_connection)s to version %(version_str)s" %
                {'sql_connection': sql_connection, 'version_str': version_str})
    return versioning_api.upgrade(sql_connection, repo_path, version)


def downgrade(options, version, repo_path=None):
    """Downgrade the database's current migration level.

    :param options: options dict
    :param version: version to downgrade to
    :retval version number

    """
    db_version(options, repo_path)  # Ensure db is under migration control
    repo_path = get_migrate_repo_path(repo_path)
    sql_connection = options['database']['connection']
    logger.info("Downgrading %(sql_connection)s to version %(version)s" %
                {'sql_connection': sql_connection, 'version': version})
    return versioning_api.downgrade(sql_connection, repo_path, version)


def version_control(options, repo_path=None):
    """Place a database under migration control.

    :param options: options dict

    """
    sql_connection = options['database']['connection']
    try:
        _version_control(options)
    except versioning_exceptions.DatabaseAlreadyControlledError:
        msg = ("database '%(sql_connection)s' is already under migration "
               "control" % {'sql_connection': sql_connection})
        raise exception.DatabaseMigrationError(msg)


def _version_control(options, repo_path):
    """Place a database under migration control.

    :param options: options dict

    """
    repo_path = get_migrate_repo_path(repo_path)
    sql_connection = options['database']['connection']
    return versioning_api.version_control(sql_connection, repo_path)


def db_sync(options, version=None, repo_path=None):
    """Place a database under migration control and perform an upgrade.

    :param options: options dict
    :param repo_path: used for plugin db migrations, defaults to main repo
    :retval version number

    """
    try:
        _version_control(options, repo_path)
    except versioning_exceptions.DatabaseAlreadyControlledError:
        pass

    upgrade(options, version=version, repo_path=repo_path)


def get_migrate_repo_path(repo_path=None):
    """Get the path for the migrate repository."""

    default_path = os.path.join(
        os.path.abspath(os.path.dirname(__file__)),
        'migrate_repo')
    repo_path = repo_path or default_path
    assert os.path.exists(repo_path)
    return repo_path
