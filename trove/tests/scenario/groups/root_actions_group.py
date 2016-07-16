# Copyright 2015 Tesora Inc.
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

from trove.tests.scenario import groups
from trove.tests.scenario.groups import guest_log_group
from trove.tests.scenario.groups.test_group import TestGroup
from trove.tests.scenario.runners import test_runners


GROUP = "scenario.root_actions_group"


class RootActionsRunnerFactory(test_runners.RunnerFactory):

    _runner_ns = 'root_actions_runners'
    _runner_cls = 'RootActionsRunner'


class BackupRunnerFactory(test_runners.RunnerFactory):

    _runner_ns = 'backup_runners'
    _runner_cls = 'BackupRunner'


class BackupRunnerFactory2(test_runners.RunnerFactory):

    _runner_ns = 'backup_runners'
    _runner_cls = 'BackupRunner'


@test(depends_on_groups=[groups.INST_CREATE_WAIT],
      groups=[GROUP, groups.ROOT_ACTION_ENABLE])
class RootActionsEnableGroup(TestGroup):
    """Test Root Actions Enable functionality."""

    def __init__(self):
        super(RootActionsEnableGroup, self).__init__(
            RootActionsRunnerFactory.instance())
        self.backup_runner = BackupRunnerFactory.instance()
        self.backup_runner2 = BackupRunnerFactory2.instance()

    @test
    def check_root_never_enabled(self):
        """Check the root has never been enabled on the instance."""
        self.test_runner.run_check_root_never_enabled()

    @test(depends_on=[check_root_never_enabled])
    def disable_root_before_enabled(self):
        """Ensure disable fails if root was never enabled."""
        self.test_runner.check_root_disable_supported()
        self.test_runner.run_disable_root_before_enabled()

    @test(depends_on=[check_root_never_enabled],
          runs_after=[disable_root_before_enabled])
    def enable_root_no_password(self):
        """Enable root (without specifying a password)."""
        self.test_runner.run_enable_root_no_password()

    @test(depends_on=[enable_root_no_password])
    def check_root_enabled(self):
        """Check the root is now enabled."""
        self.test_runner.run_check_root_enabled()

    @test(depends_on=[check_root_enabled])
    def backup_root_enabled_instance(self):
        """Backup the root-enabled instance."""
        self.backup_runner.run_backup_create()
        self.backup_runner.run_backup_create_completed()

    @test(depends_on=[check_root_enabled],
          runs_after=[backup_root_enabled_instance])
    def delete_root(self):
        """Ensure an attempt to delete the root user fails."""
        self.test_runner.run_delete_root()

    @test(depends_on=[check_root_never_enabled],
          runs_after=[delete_root])
    def enable_root_with_password(self):
        """Enable root (with a given password)."""
        self.test_runner.run_enable_root_with_password()

    @test(depends_on=[enable_root_with_password])
    def check_root_still_enabled(self):
        """Check the root is still enabled."""
        self.test_runner.run_check_root_enabled()


@test(depends_on_groups=[groups.ROOT_ACTION_ENABLE],
      groups=[GROUP, groups.ROOT_ACTION_DISABLE])
class RootActionsDisableGroup(TestGroup):
    """Test Root Actions Disable functionality."""

    def __init__(self):
        super(RootActionsDisableGroup, self).__init__(
            RootActionsRunnerFactory.instance())
        self.backup_runner = BackupRunnerFactory.instance()
        self.backup_runner2 = BackupRunnerFactory2.instance()

    @test
    def disable_root(self):
        """Disable root."""
        self.test_runner.check_root_disable_supported()
        self.test_runner.run_disable_root()

    @test(depends_on=[disable_root])
    def check_root_still_enabled_after_disable(self):
        """Check the root is still marked as enabled after disable."""
        self.test_runner.check_root_disable_supported()
        self.test_runner.run_check_root_still_enabled_after_disable()

    @test(depends_on=[check_root_still_enabled_after_disable])
    def backup_root_disabled_instance(self):
        """Backup the root-disabled instance."""
        self.test_runner.check_root_disable_supported()
        self.backup_runner2.run_backup_create()
        self.backup_runner2.run_backup_create_completed()


@test(depends_on_groups=[groups.ROOT_ACTION_DISABLE],
      groups=[GROUP, groups.ROOT_ACTION_INST, groups.ROOT_ACTION_INST_CREATE],
      runs_after_groups=[groups.INST_ACTIONS_RESIZE_WAIT])
class RootActionsInstCreateGroup(TestGroup):
    """Test Root Actions Instance Create functionality."""

    def __init__(self):
        super(RootActionsInstCreateGroup, self).__init__(
            RootActionsRunnerFactory.instance())
        self.backup_runner = BackupRunnerFactory.instance()
        self.backup_runner2 = BackupRunnerFactory2.instance()

    @test
    def restore_root_enabled_instance(self):
        """Restore the root-enabled instance."""
        self.backup_runner.run_restore_from_backup(suffix='_root_enable')

    @test
    def restore_root_disabled_instance(self):
        """Restore the root-disabled instance."""
        self.test_runner.check_root_disable_supported()
        self.backup_runner2.run_restore_from_backup(suffix='_root_disable')


@test(depends_on_groups=[groups.ROOT_ACTION_INST_CREATE],
      groups=[GROUP, groups.ROOT_ACTION_INST,
              groups.ROOT_ACTION_INST_CREATE_WAIT],
      runs_after_groups=[guest_log_group.GROUP])
class RootActionsInstCreateWaitGroup(TestGroup):
    """Wait for Root Actions Instance Create to complete."""

    def __init__(self):
        super(RootActionsInstCreateWaitGroup, self).__init__(
            RootActionsRunnerFactory.instance())
        self.backup_runner = BackupRunnerFactory.instance()
        self.backup_runner2 = BackupRunnerFactory2.instance()

    @test
    def wait_for_restored_instance(self):
        """Wait until restoring a root-enabled instance completes."""
        self.backup_runner.run_restore_from_backup_completed()

    @test(depends_on=[wait_for_restored_instance])
    def check_root_enabled_after_restore(self):
        """Check the root is also enabled on the restored instance."""
        instance_id = self.backup_runner.restore_instance_id
        root_creds = self.test_runner.restored_root_creds
        self.test_runner.run_check_root_enabled_after_restore(
            instance_id, root_creds)

    @test
    def wait_for_restored_instance2(self):
        """Wait until restoring a root-disabled instance completes."""
        self.test_runner.check_root_disable_supported()
        self.backup_runner2.run_restore_from_backup_completed()

    @test(depends_on=[wait_for_restored_instance2])
    def check_root_enabled_after_restore2(self):
        """Check the root is also enabled on the restored instance."""
        instance_id = self.backup_runner2.restore_instance_id
        root_creds = self.test_runner.restored_root_creds2
        self.test_runner.run_check_root_enabled_after_restore2(
            instance_id, root_creds)


@test(depends_on_groups=[groups.ROOT_ACTION_INST_CREATE_WAIT],
      groups=[GROUP, groups.ROOT_ACTION_INST, groups.ROOT_ACTION_INST_DELETE])
class RootActionsInstDeleteGroup(TestGroup):
    """Test Root Actions Instance Delete functionality."""

    def __init__(self):
        super(RootActionsInstDeleteGroup, self).__init__(
            RootActionsRunnerFactory.instance())
        self.backup_runner = BackupRunnerFactory.instance()
        self.backup_runner2 = BackupRunnerFactory2.instance()

    @test
    def delete_restored_instance(self):
        """Delete the restored root-enabled instance."""
        self.backup_runner.run_delete_restored_instance()

    @test
    def delete_instance_backup(self):
        """Delete the root-enabled instance backup."""
        self.backup_runner.run_delete_backup()

    @test
    def delete_restored_instance2(self):
        """Delete the restored root-disabled instance."""
        self.test_runner.check_root_disable_supported()
        self.backup_runner2.run_delete_restored_instance()

    @test
    def delete_instance_backup2(self):
        """Delete the root-disabled instance backup."""
        self.test_runner.check_root_disable_supported()
        self.backup_runner2.run_delete_backup()


@test(depends_on_groups=[groups.ROOT_ACTION_INST_DELETE],
      groups=[GROUP, groups.ROOT_ACTION_INST,
              groups.ROOT_ACTION_INST_DELETE_WAIT],
      runs_after_groups=[groups.INST_DELETE])
class RootActionsInstDeleteWaitGroup(TestGroup):
    """Wait for Root Actions Instance Delete to complete."""

    def __init__(self):
        super(RootActionsInstDeleteWaitGroup, self).__init__(
            RootActionsRunnerFactory.instance())
        self.backup_runner = BackupRunnerFactory.instance()
        self.backup_runner2 = BackupRunnerFactory2.instance()

    @test
    def wait_for_restored_instance_delete(self):
        """Wait for the root-enabled instance to be deleted."""
        self.backup_runner.run_wait_for_restored_instance_delete()

    @test
    def wait_for_restored_instance2_delete(self):
        """Wait for the root-disabled instance to be deleted."""
        self.backup_runner2.run_wait_for_restored_instance_delete()
