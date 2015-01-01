# Copyright 2014 Hewlett-Packard Development Company, L.P.
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
from proboscis import test
from proboscis.asserts import assert_equal
from proboscis.asserts import assert_raises
from proboscis.asserts import assert_true
from proboscis.decorators import time_out
from proboscis import SkipTest
from trove.common.utils import generate_uuid
from trove.common.utils import poll_until
from trove.tests.api.instances import CheckInstance
from trove.tests.api.instances import instance_info
from trove.tests.api.instances import TIMEOUT_INSTANCE_CREATE
from trove.tests.api.instances import TIMEOUT_INSTANCE_DELETE
from trove.tests.api.instances import WaitForGuestInstallationToFinish
from trove.tests.config import CONFIG
from trove.tests.util.server_connection import create_server_connection
from troveclient.compat import exceptions


class SlaveInstanceTestInfo(object):
    """Stores slave instance information."""
    def __init__(self):
        self.id = None
        self.replicated_db = generate_uuid()


GROUP = "dbaas.api.replication"
slave_instance = SlaveInstanceTestInfo()
existing_db_on_master = generate_uuid()


def _get_user_count(server_info):
    cmd = ('mysql -BNq -e \\\'select count\\(*\\) from mysql.user'
           ' where user like \\\"slave_%\\\"\\\'')
    server = create_server_connection(server_info.id)
    stdout, stderr = server.execute(cmd)
    return int(stdout.rstrip())


def slave_is_running(running=True):

    def check_slave_is_running():
        server = create_server_connection(slave_instance.id)
        cmd = ("mysqladmin extended-status "
               "| awk '/Slave_running/{print $4}'")
        stdout, stderr = server.execute(cmd)
        expected = "ON" if running else "OFF"
        return stdout.rstrip() == expected

    return check_slave_is_running


@test(depends_on_classes=[WaitForGuestInstallationToFinish],
      groups=[GROUP])
class CreateReplicationSlave(object):

    @test
    def test_create_db_on_master(self):
        databases = [{'name': existing_db_on_master}]
        # Ensure that the auth_token in the dbaas client is not stale
        instance_info.dbaas.authenticate()
        instance_info.dbaas.databases.create(instance_info.id, databases)
        assert_equal(202, instance_info.dbaas.last_http_code)

    @test(runs_after=['test_create_db_on_master'])
    def test_create_slave(self):
        result = instance_info.dbaas.instances.create(
            instance_info.name + "_slave",
            instance_info.dbaas_flavor_href,
            instance_info.volume,
            slave_of=instance_info.id)
        assert_equal(200, instance_info.dbaas.last_http_code)
        assert_equal("BUILD", result.status)
        slave_instance.id = result.id


@test(groups=[GROUP])
class WaitForCreateSlaveToFinish(object):
    """Wait until the instance is created and set up as slave."""

    @test(depends_on=[CreateReplicationSlave.test_create_slave])
    @time_out(TIMEOUT_INSTANCE_CREATE)
    def test_slave_created(self):
        def result_is_active():
            instance = instance_info.dbaas.instances.get(slave_instance.id)
            if instance.status == "ACTIVE":
                return True
            else:
                assert_true(instance.status in ['BUILD', 'BACKUP'])
                return False
        poll_until(result_is_active)


@test(enabled=(not CONFIG.fake_mode),
      depends_on=[WaitForCreateSlaveToFinish],
      groups=[GROUP])
class VerifySlave(object):

    def db_is_found(self, database_to_find):

        def find_database():
            databases = instance_info.dbaas.databases.list(slave_instance.id)
            return (database_to_find
                    in [d.name for d in databases])

        return find_database

    @test
    @time_out(5 * 60)
    def test_correctly_started_replication(self):
        poll_until(slave_is_running())

    @test(runs_after=[test_correctly_started_replication])
    def test_backup_deleted(self):
        backup = instance_info.dbaas.instances.backups(instance_info.id)
        assert_equal(len(backup), 0)

    @test(depends_on=[test_correctly_started_replication])
    def test_slave_is_read_only(self):
        cmd = "mysql -BNq -e \\\'select @@read_only\\\'"
        server = create_server_connection(slave_instance.id)
        stdout, stderr = server.execute(cmd)
        assert_equal(stdout, "1\n")

    @test(depends_on=[test_slave_is_read_only])
    def test_create_db_on_master(self):
        databases = [{'name': slave_instance.replicated_db}]
        instance_info.dbaas.databases.create(instance_info.id, databases)
        assert_equal(202, instance_info.dbaas.last_http_code)

    @test(depends_on=[test_create_db_on_master])
    @time_out(5 * 60)
    def test_database_replicated_on_slave(self):
        poll_until(self.db_is_found(slave_instance.replicated_db))

    @test(runs_after=[test_database_replicated_on_slave])
    @time_out(5 * 60)
    def test_existing_db_exists_on_slave(self):
        poll_until(self.db_is_found(existing_db_on_master))

    @test(depends_on=[test_existing_db_exists_on_slave])
    def test_slave_user_exists(self):
        assert_equal(_get_user_count(slave_instance), 1)
        assert_equal(_get_user_count(instance_info), 1)


@test(groups=[GROUP],
      depends_on=[WaitForCreateSlaveToFinish],
      runs_after=[VerifySlave])
class TestInstanceListing(object):
    """Test replication information in instance listing."""

    @test
    def test_get_slave_instance(self):
        instance = instance_info.dbaas.instances.get(slave_instance.id)
        assert_equal(200, instance_info.dbaas.last_http_code)
        instance_dict = instance._info
        print("instance_dict=%s" % instance_dict)
        CheckInstance(instance_dict).slave_of()
        assert_equal(instance_info.id, instance_dict['replica_of']['id'])

    @test
    def test_get_master_instance(self):
        instance = instance_info.dbaas.instances.get(instance_info.id)
        assert_equal(200, instance_info.dbaas.last_http_code)
        instance_dict = instance._info
        print("instance_dict=%s" % instance_dict)
        CheckInstance(instance_dict).slaves()
        assert_equal(slave_instance.id, instance_dict['replicas'][0]['id'])


@test(groups=[GROUP],
      depends_on=[WaitForCreateSlaveToFinish],
      runs_after=[VerifySlave])
class DetachReplica(object):

    @test
    def delete_before_detach_replica(self):
        assert_raises(exceptions.Forbidden,
                      instance_info.dbaas.instances.delete,
                      instance_info.id)

    @test
    @time_out(5 * 60)
    def test_detach_replica(self):
        if CONFIG.fake_mode:
            raise SkipTest("Detach replica not supported in fake mode")

        instance_info.dbaas.instances.edit(slave_instance.id,
                                           detach_replica_source=True)
        assert_equal(202, instance_info.dbaas.last_http_code)

        poll_until(slave_is_running(False))

    @test(depends_on=[test_detach_replica])
    @time_out(5 * 60)
    def test_slave_is_not_read_only(self):
        if CONFIG.fake_mode:
            raise SkipTest("Test not_read_only not supported in fake mode")

        # wait until replica is no longer read only
        def check_not_read_only():
            cmd = "mysql -BNq -e \\\'select @@read_only\\\'"
            server = create_server_connection(slave_instance.id)
            stdout, stderr = server.execute(cmd)
            if (stdout.rstrip() != "0"):
                return False
            else:
                return True
        poll_until(check_not_read_only)

    @test(depends_on=[test_detach_replica])
    @time_out(3 * 60)
    def test_slave_user_removed(self):
        if CONFIG.fake_mode:
            raise SkipTest("Test not_read_only not supported in fake mode")

        def _slave_user_deleted():
            return _get_user_count(instance_info) == 0

        poll_until(_slave_user_deleted)


@test(groups=[GROUP],
      depends_on=[WaitForCreateSlaveToFinish],
      runs_after=[DetachReplica])
class DeleteSlaveInstance(object):

    @test
    @time_out(TIMEOUT_INSTANCE_DELETE)
    def test_delete_slave_instance(self):
        instance_info.dbaas.instances.delete(slave_instance.id)
        assert_equal(202, instance_info.dbaas.last_http_code)

        def instance_is_gone():
            try:
                instance_info.dbaas.instances.get(slave_instance.id)
                return False
            except exceptions.NotFound:
                return True

        poll_until(instance_is_gone)
        assert_raises(exceptions.NotFound, instance_info.dbaas.instances.get,
                      slave_instance.id)
