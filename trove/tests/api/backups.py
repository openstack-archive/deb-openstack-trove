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
from proboscis.asserts import assert_equal
from proboscis.asserts import assert_not_equal
from proboscis.asserts import assert_raises
from proboscis.asserts import assert_true
from proboscis import test
from proboscis import SkipTest
from proboscis.decorators import time_out
import troveclient.compat
from trove.common.utils import poll_until
from trove.common.utils import generate_uuid
from trove.tests.util import create_dbaas_client
from trove.tests.util.users import Requirements
from trove.tests.config import CONFIG
from troveclient.compat import exceptions
from trove.tests.api.instances import WaitForGuestInstallationToFinish
from trove.tests.api.instances import instance_info
from trove.tests.api.instances import TIMEOUT_INSTANCE_CREATE
from trove.tests.api.instances import TIMEOUT_INSTANCE_DELETE
from trove.tests.api.instances import assert_unprocessable
from trove import tests


GROUP = "dbaas.api.backups"
BACKUP_NAME = 'backup_test'
BACKUP_DESC = 'test description'

TIMEOUT_BACKUP_CREATE = 60 * 30
TIMEOUT_BACKUP_DELETE = 120

backup_info = None
incremental_info = None
incremental_db = generate_uuid()
restore_instance_id = None
backup_count_prior_to_create = 0
backup_count_for_instance_prior_to_create = 0


@test(depends_on_classes=[WaitForGuestInstallationToFinish],
      groups=[GROUP, tests.INSTANCES])
class CreateBackups(object):

    @test
    def test_backup_create_instance_invalid(self):
        """test create backup with unknown instance"""
        invalid_inst_id = 'invalid-inst-id'
        try:
            instance_info.dbaas.backups.create(BACKUP_NAME, invalid_inst_id,
                                               BACKUP_DESC)
        except exceptions.BadRequest as e:
            resp, body = instance_info.dbaas.client.last_response
            assert_equal(resp.status, 400)
            if not isinstance(instance_info.dbaas.client,
                              troveclient.compat.xml.TroveXmlClient):
                assert_equal(e.message,
                             "Validation error: "
                             "backup['instance'] u'%s' does not match "
                             "'^([0-9a-fA-F]){8}-([0-9a-fA-F]){4}-"
                             "([0-9a-fA-F]){4}-([0-9a-fA-F]){4}-"
                             "([0-9a-fA-F]){12}$'" %
                             invalid_inst_id)

    @test
    def test_backup_create_instance_not_found(self):
        """test create backup with unknown instance"""
        assert_raises(exceptions.NotFound, instance_info.dbaas.backups.create,
                      BACKUP_NAME, generate_uuid(), BACKUP_DESC)

    @test
    def test_backup_create_instance(self):
        """test create backup for a given instance"""
        # Necessary to test that the count increases.
        global backup_count_prior_to_create
        backup_count_prior_to_create = len(instance_info.dbaas.backups.list())
        global backup_count_for_instance_prior_to_create
        backup_count_for_instance_prior_to_create = len(
            instance_info.dbaas.instances.backups(instance_info.id))

        result = instance_info.dbaas.backups.create(BACKUP_NAME,
                                                    instance_info.id,
                                                    BACKUP_DESC)
        global backup_info
        backup_info = result
        assert_equal(BACKUP_NAME, result.name)
        assert_equal(BACKUP_DESC, result.description)
        assert_equal(instance_info.id, result.instance_id)
        assert_equal('NEW', result.status)
        instance = instance_info.dbaas.instances.get(instance_info.id)
        assert_equal('BACKUP', instance.status)


@test(runs_after=[CreateBackups],
      groups=[GROUP, tests.INSTANCES])
class AfterBackupCreation(object):

    @test
    def test_instance_action_right_after_backup_create(self):
        """test any instance action while backup is running"""
        assert_unprocessable(instance_info.dbaas.instances.resize_instance,
                             instance_info.id, 1)

    @test
    def test_backup_create_another_backup_running(self):
        """test create backup when another backup is running"""
        assert_unprocessable(instance_info.dbaas.backups.create,
                             'backup_test2', instance_info.id,
                             'test description2')

    @test
    def test_backup_delete_still_running(self):
        """test delete backup when it is running"""
        result = instance_info.dbaas.backups.list()
        backup = result[0]
        assert_unprocessable(instance_info.dbaas.backups.delete, backup.id)


@test(runs_after=[AfterBackupCreation],
      groups=[GROUP, tests.INSTANCES])
class WaitForBackupCreateToFinish(object):
    """
        Wait until the backup create is finished.
    """

    @test
    @time_out(TIMEOUT_BACKUP_CREATE)
    def test_backup_created(self):
        # This version just checks the REST API status.
        def result_is_active():
            backup = instance_info.dbaas.backups.get(backup_info.id)
            if backup.status == "COMPLETED":
                return True
            else:
                assert_not_equal("FAILED", backup.status)
                return False

        poll_until(result_is_active)


@test(depends_on=[WaitForBackupCreateToFinish],
      groups=[GROUP, tests.INSTANCES])
class ListBackups(object):

    @test
    def test_backup_list(self):
        """test list backups"""
        result = instance_info.dbaas.backups.list()
        assert_equal(backup_count_prior_to_create + 1, len(result))
        backup = result[0]
        assert_equal(BACKUP_NAME, backup.name)
        assert_equal(BACKUP_DESC, backup.description)
        assert_not_equal(0.0, backup.size)
        assert_equal(instance_info.id, backup.instance_id)
        assert_equal('COMPLETED', backup.status)

    @test
    def test_backup_list_for_instance(self):
        """test backup list for instance"""
        result = instance_info.dbaas.instances.backups(instance_info.id)
        assert_equal(backup_count_for_instance_prior_to_create + 1,
                     len(result))
        backup = result[0]
        assert_equal(BACKUP_NAME, backup.name)
        assert_equal(BACKUP_DESC, backup.description)
        assert_not_equal(0.0, backup.size)
        assert_equal(instance_info.id, backup.instance_id)
        assert_equal('COMPLETED', backup.status)

    @test
    def test_backup_get(self):
        """test get backup"""
        backup = instance_info.dbaas.backups.get(backup_info.id)
        assert_equal(backup_info.id, backup.id)
        assert_equal(backup_info.name, backup.name)
        assert_equal(backup_info.description, backup.description)
        assert_equal(instance_info.id, backup.instance_id)
        assert_not_equal(0.0, backup.size)
        assert_equal('COMPLETED', backup.status)

        # Test to make sure that user in other tenant is not able
        # to GET this backup
        reqs = Requirements(is_admin=False)
        other_user = CONFIG.users.find_user(
            reqs,
            black_list=[instance_info.user.auth_user])
        other_client = create_dbaas_client(other_user)
        assert_raises(exceptions.NotFound, other_client.backups.get,
                      backup_info.id)


@test(runs_after=[ListBackups],
      depends_on=[WaitForBackupCreateToFinish],
      groups=[GROUP, tests.INSTANCES])
class IncrementalBackups(object):

    @test
    def test_create_db(self):
        databases = [{'name': incremental_db}]
        instance_info.dbaas.databases.create(instance_info.id, databases)
        assert_equal(202, instance_info.dbaas.last_http_code)

    @test(runs_after=['test_create_db'])
    def test_create_incremental_backup(self):
        result = instance_info.dbaas.backups.create("incremental-backup",
                                                    backup_info.instance_id,
                                                    parent_id=backup_info.id)
        global incremental_info
        incremental_info = result
        assert_equal(202, instance_info.dbaas.last_http_code)

        # Wait for the backup to finish
        def result_is_active():
            backup = instance_info.dbaas.backups.get(incremental_info.id)
            if backup.status == "COMPLETED":
                return True
            else:
                assert_not_equal("FAILED", backup.status)
                return False

        poll_until(result_is_active, time_out=TIMEOUT_BACKUP_CREATE)
        assert_equal(backup_info.id, incremental_info.parent_id)


@test(runs_after=[IncrementalBackups],
      groups=[GROUP, tests.INSTANCES])
class RestoreUsingBackup(object):

    @test
    def test_restore(self):
        """test restore"""
        restorePoint = {"backupRef": incremental_info.id}
        result = instance_info.dbaas.instances.create(
            instance_info.name + "_restore",
            instance_info.dbaas_flavor_href,
            instance_info.volume,
            restorePoint=restorePoint)
        assert_equal(200, instance_info.dbaas.last_http_code)
        assert_equal("BUILD", result.status)
        global restore_instance_id
        restore_instance_id = result.id


@test(depends_on_classes=[RestoreUsingBackup],
      runs_after=[RestoreUsingBackup],
      groups=[GROUP, tests.INSTANCES])
class WaitForRestoreToFinish(object):
    """
        Wait until the instance is finished restoring.
    """

    @test
    def test_instance_restored(self):
        # This version just checks the REST API status.
        def result_is_active():
            instance = instance_info.dbaas.instances.get(restore_instance_id)
            if instance.status == "ACTIVE":
                return True
            else:
                # If its not ACTIVE, anything but BUILD must be
                # an error.
                assert_equal("BUILD", instance.status)
                if instance_info.volume is not None:
                    assert_equal(instance.volume.get('used', None), None)
                return False

        poll_until(result_is_active, time_out=TIMEOUT_INSTANCE_CREATE,
                   sleep_time=10)


@test(depends_on_classes=[RestoreUsingBackup, WaitForRestoreToFinish],
      runs_after=[WaitForRestoreToFinish],
      enabled=(not CONFIG.fake_mode),
      groups=[GROUP, tests.INSTANCES])
class VerifyRestore(object):

    @test
    def test_database_restored(self):
        databases = instance_info.dbaas.databases.list(restore_instance_id)
        dbs = [d.name for d in databases]
        assert_true(incremental_db in dbs,
                    "%s not found on restored instance" % incremental_db)


@test(runs_after=[VerifyRestore],
      groups=[GROUP, tests.INSTANCES])
class DeleteRestoreInstance(object):

    @test
    def test_delete_restored_instance(self):
        """test delete restored instance"""
        instance_info.dbaas.instances.delete(restore_instance_id)
        assert_equal(202, instance_info.dbaas.last_http_code)

        def instance_is_gone():
            try:
                instance_info.dbaas.instances.get(restore_instance_id)
                return False
            except exceptions.NotFound:
                return True

        poll_until(instance_is_gone, time_out=TIMEOUT_INSTANCE_DELETE)
        assert_raises(exceptions.NotFound, instance_info.dbaas.instances.get,
                      restore_instance_id)


@test(runs_after=[DeleteRestoreInstance],
      groups=[GROUP, tests.INSTANCES])
class DeleteBackups(object):

    @test
    def test_backup_delete_not_found(self):
        """test delete unknown backup"""
        assert_raises(exceptions.NotFound, instance_info.dbaas.backups.delete,
                      'nonexistent_backup')

    @test
    def test_backup_delete_other(self):
        """Test another user cannot delete backup"""
        # Test to make sure that user in other tenant is not able
        # to DELETE this backup
        reqs = Requirements(is_admin=False)
        other_user = CONFIG.users.find_user(
            reqs,
            black_list=[instance_info.user.auth_user])
        other_client = create_dbaas_client(other_user)
        assert_raises(exceptions.NotFound, other_client.backups.delete,
                      backup_info.id)

    @test(runs_after=[test_backup_delete_other])
    def test_backup_delete(self):
        """test backup deletion"""
        instance_info.dbaas.backups.delete(backup_info.id)
        assert_equal(202, instance_info.dbaas.last_http_code)

        def backup_is_gone():
            try:
                instance_info.dbaas.backups.get(backup_info.id)
                return False
            except exceptions.NotFound:
                return True

        poll_until(backup_is_gone, time_out=TIMEOUT_BACKUP_DELETE)

    @test(runs_after=[test_backup_delete])
    def test_incremental_deleted(self):
        """test backup children are deleted"""
        if incremental_info is None:
            raise SkipTest("Incremental Backup not created")
        assert_raises(exceptions.NotFound, instance_info.dbaas.backups.get,
                      incremental_info.id)
