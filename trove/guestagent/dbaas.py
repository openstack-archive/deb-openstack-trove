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
Handles all processes within the Guest VM, considering it as a Platform

The :py:class:`GuestManager` class is a :py:class:`nova.manager.Manager` that
handles RPC calls relating to Platform specific operations.

**Related Flags**

"""

from itertools import chain
import os

from oslo_log import log as logging

from trove.common import cfg
from trove.common.i18n import _


LOG = logging.getLogger(__name__)
defaults = {
    'mysql':
    'trove.guestagent.datastore.mysql.manager.Manager',
    'percona':
    'trove.guestagent.datastore.experimental.percona.manager.Manager',
    'pxc':
    'trove.guestagent.datastore.experimental.pxc.manager.Manager',
    'redis':
    'trove.guestagent.datastore.experimental.redis.manager.Manager',
    'cassandra':
    'trove.guestagent.datastore.experimental.cassandra.manager.Manager',
    'couchbase':
    'trove.guestagent.datastore.experimental.couchbase.manager.Manager',
    'mongodb':
    'trove.guestagent.datastore.experimental.mongodb.manager.Manager',
    'postgresql':
    'trove.guestagent.datastore.experimental.postgresql.manager.Manager',
    'couchdb':
    'trove.guestagent.datastore.experimental.couchdb.manager.Manager',
    'vertica':
    'trove.guestagent.datastore.experimental.vertica.manager.Manager',
    'db2':
    'trove.guestagent.datastore.experimental.db2.manager.Manager',
    'mariadb':
    'trove.guestagent.datastore.experimental.mariadb.manager.Manager'
}
CONF = cfg.CONF


def get_custom_managers():
    return CONF.datastore_registry_ext


def datastore_registry():
    return dict(chain(defaults.items(),
                get_custom_managers().items()))


def to_gb(bytes):
    if bytes == 0:
        return 0.0
    size = bytes / 1024.0 ** 3
    # Make sure we don't return 0.0 if the size is greater than 0
    return max(round(size, 2), 0.01)


def to_mb(bytes):
    if bytes == 0:
        return 0.0
    size = bytes / 1024.0 ** 2
    # Make sure we don't return 0.0 if the size is greater than 0
    return max(round(size, 2), 0.01)


def get_filesystem_volume_stats(fs_path):
    try:
        stats = os.statvfs(fs_path)
    except OSError:
        LOG.exception(_("Error getting volume stats."))
        raise RuntimeError("Filesystem not found (%s)" % fs_path)

    total = stats.f_blocks * stats.f_bsize
    free = stats.f_bfree * stats.f_bsize
    # return the size in GB
    used_gb = to_gb(total - free)
    total_gb = to_gb(total)

    output = {
        'block_size': stats.f_bsize,
        'total_blocks': stats.f_blocks,
        'free_blocks': stats.f_bfree,
        'total': total_gb,
        'free': free,
        'used': used_gb
    }
    return output
