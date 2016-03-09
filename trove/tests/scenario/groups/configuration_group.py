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

from trove.tests.scenario.groups import instance_create_group
from trove.tests.scenario.groups.test_group import TestGroup


GROUP = "scenario.configuration_group"


@test(depends_on_groups=[instance_create_group.GROUP], groups=[GROUP])
class ConfigurationGroup(TestGroup):

    def __init__(self):
        super(ConfigurationGroup, self).__init__(
            'configuration_runners', 'ConfigurationRunner')

    @test
    def create_bad_group(self):
        """Ensure a group with bad entries fails create."""
        self.test_runner.run_create_bad_group()

    @test
    def create_invalid_groups(self):
        """Ensure a group with invalid entries fails create."""
        self.test_runner.run_create_invalid_groups()

    @test
    def delete_non_existent_group(self):
        """Ensure delete non-existent group fails."""
        self.test_runner.run_delete_non_existent_group()

    @test
    def delete_bad_group_id(self):
        """Ensure delete bad group fails."""
        self.test_runner.run_delete_bad_group_id()

    @test
    def attach_non_existent_group(self):
        """Ensure attach non-existent group fails."""
        self.test_runner.run_attach_non_existent_group()

    def attach_non_existent_group_to_non_existent_inst(self):
        """Ensure attach non-existent group to non-existent inst fails."""
        self.test_runner.run_attach_non_existent_group_to_non_existent_inst()

    @test
    def detach_group_with_none_attached(self):
        """Test detach with none attached."""
        self.test_runner.run_detach_group_with_none_attached()

    @test
    def create_dynamic_group(self):
        """Create a group with only dynamic entries."""
        self.test_runner.run_create_dynamic_group()

    @test
    def create_non_dynamic_group(self):
        """Create a group with only non-dynamic entries."""
        self.test_runner.run_create_non_dynamic_group()

    @test(depends_on=[create_dynamic_group])
    def attach_dynamic_group_to_non_existent_inst(self):
        """Ensure attach dynamic group to non-existent inst fails."""
        self.test_runner.run_attach_dynamic_group_to_non_existent_inst()

    @test(depends_on=[create_non_dynamic_group])
    def attach_non_dynamic_group_to_non_existent_inst(self):
        """Ensure attach non-dynamic group to non-existent inst fails."""
        self.test_runner.run_attach_non_dynamic_group_to_non_existent_inst()

    @test(depends_on=[create_dynamic_group, create_non_dynamic_group])
    def list_configuration_groups(self):
        """Test list configuration groups."""
        self.test_runner.run_list_configuration_groups()

    @test(depends_on=[create_dynamic_group])
    def dynamic_configuration_show(self):
        """Test show on dynamic group."""
        self.test_runner.run_dynamic_configuration_show()

    @test(depends_on=[create_non_dynamic_group])
    def non_dynamic_configuration_show(self):
        """Test show on non-dynamic group."""
        self.test_runner.run_non_dynamic_configuration_show()

    @test(depends_on=[create_dynamic_group])
    def dynamic_conf_get_unauthorized_user(self):
        """Ensure show dynamic fails with unauthorized user."""
        self.test_runner.run_dynamic_conf_get_unauthorized_user()

    @test(depends_on=[create_non_dynamic_group])
    def non_dynamic_conf_get_unauthorized_user(self):
        """Ensure show non-dynamic fails with unauthorized user."""
        self.test_runner.run_non_dynamic_conf_get_unauthorized_user()

    @test(depends_on=[create_dynamic_group],
          runs_after=[list_configuration_groups])
    def list_dynamic_inst_conf_groups_before(self):
        """Count list instances for dynamic group before attach."""
        self.test_runner.run_list_dynamic_inst_conf_groups_before()

    @test(depends_on=[create_dynamic_group],
          runs_after=[list_dynamic_inst_conf_groups_before,
                      attach_non_existent_group,
                      detach_group_with_none_attached])
    def attach_dynamic_group(self):
        """Test attach dynamic group."""
        self.test_runner.run_attach_dynamic_group()

    @test(depends_on=[attach_dynamic_group])
    def list_dynamic_inst_conf_groups_after(self):
        """Test list instances for dynamic group after attach."""
        self.test_runner.run_list_dynamic_inst_conf_groups_after()

    @test(depends_on=[attach_dynamic_group],
          runs_after=[list_dynamic_inst_conf_groups_after])
    def attach_dynamic_group_again(self):
        """Ensure attaching dynamic group again fails."""
        self.test_runner.run_attach_dynamic_group_again()

    @test(depends_on=[attach_dynamic_group],
          runs_after=[attach_dynamic_group_again])
    def delete_attached_dynamic_group(self):
        """Ensure deleting attached dynamic group fails."""
        self.test_runner.run_delete_attached_dynamic_group()

    @test(depends_on=[attach_dynamic_group],
          runs_after=[delete_attached_dynamic_group])
    def update_dynamic_group(self):
        """Test update dynamic group."""
        self.test_runner.run_update_dynamic_group()

    @test(depends_on=[create_dynamic_group],
          runs_after=[update_dynamic_group])
    def detach_dynamic_group(self):
        """Test detach dynamic group."""
        self.test_runner.run_detach_dynamic_group()

    @test(depends_on=[create_non_dynamic_group],
          runs_after=[detach_dynamic_group])
    def list_non_dynamic_inst_conf_groups_before(self):
        """Count list instances for non-dynamic group before attach."""
        self.test_runner.run_list_non_dynamic_inst_conf_groups_before()

    @test(depends_on=[create_non_dynamic_group],
          runs_after=[list_non_dynamic_inst_conf_groups_before,
                      attach_non_existent_group])
    def attach_non_dynamic_group(self):
        """Test attach non-dynamic group."""
        self.test_runner.run_attach_non_dynamic_group()

    @test(depends_on=[attach_non_dynamic_group])
    def list_non_dynamic_inst_conf_groups_after(self):
        """Test list instances for non-dynamic group after attach."""
        self.test_runner.run_list_non_dynamic_inst_conf_groups_after()

    @test(depends_on=[attach_non_dynamic_group],
          runs_after=[list_non_dynamic_inst_conf_groups_after])
    def attach_non_dynamic_group_again(self):
        """Ensure attaching non-dynamic group again fails."""
        self.test_runner.run_attach_non_dynamic_group_again()

    @test(depends_on=[attach_non_dynamic_group],
          runs_after=[attach_non_dynamic_group_again])
    def delete_attached_non_dynamic_group(self):
        """Ensure deleting attached non-dynamic group fails."""
        self.test_runner.run_delete_attached_non_dynamic_group()

    @test(depends_on=[attach_non_dynamic_group],
          runs_after=[delete_attached_non_dynamic_group])
    def update_non_dynamic_group(self):
        """Test update non-dynamic group."""
        self.test_runner.run_update_non_dynamic_group()

    @test(depends_on=[attach_non_dynamic_group],
          runs_after=[update_non_dynamic_group])
    def detach_non_dynamic_group(self):
        """Test detach non-dynamic group."""
        self.test_runner.run_detach_non_dynamic_group()

    @test(runs_after=[create_dynamic_group, create_non_dynamic_group,
                      update_dynamic_group, update_non_dynamic_group])
    def create_instance_with_conf(self):
        """Test create instance with conf group."""
        self.test_runner.run_create_instance_with_conf()

    @test(depends_on=[create_instance_with_conf],
          runs_after=[create_dynamic_group, create_non_dynamic_group,
          update_dynamic_group, update_non_dynamic_group])
    def wait_for_conf_instance(self):
        """Test create instance with conf group completes."""
        self.test_runner.run_wait_for_conf_instance()

    @test(depends_on=[wait_for_conf_instance])
    def delete_conf_instance(self):
        """Test delete instance with conf group."""
        self.test_runner.run_delete_conf_instance()

    @test(depends_on=[create_dynamic_group],
          runs_after=[list_configuration_groups, detach_dynamic_group,
                      dynamic_configuration_show,
                      dynamic_conf_get_unauthorized_user,
                      attach_dynamic_group_to_non_existent_inst,
                      delete_conf_instance])
    def delete_dynamic_group(self):
        """Test delete dynamic group."""
        self.test_runner.run_delete_dynamic_group()

    @test(depends_on=[create_non_dynamic_group],
          runs_after=[list_configuration_groups, detach_non_dynamic_group,
                      non_dynamic_configuration_show,
                      non_dynamic_conf_get_unauthorized_user,
                      attach_non_dynamic_group_to_non_existent_inst,
                      delete_conf_instance])
    def delete_non_dynamic_group(self):
        """Test delete non-dynamic group."""
        self.test_runner.run_delete_non_dynamic_group()
