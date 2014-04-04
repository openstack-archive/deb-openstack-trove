#    Copyright 2012 OpenStack Foundation
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
import traceback
import os.path

from heatclient import exc as heat_exceptions
from cinderclient import exceptions as cinder_exceptions
from eventlet import greenthread
from novaclient import exceptions as nova_exceptions
from trove.backup import models as bkup_models
from trove.common import cfg
from trove.common import template
from trove.common import utils
from trove.common.utils import try_recover
from trove.common.configurations import do_configs_require_restart
from trove.common.exception import GuestError
from trove.common.exception import GuestTimeout
from trove.common.exception import PollTimeOut
from trove.common.exception import VolumeCreationFailure
from trove.common.exception import TroveError
from trove.common.exception import MalformedSecurityGroupRuleError
from trove.common.instance import ServiceStatuses
from trove.common import instance as rd_instance
from trove.common.remote import create_dns_client
from trove.common.remote import create_heat_client
from trove.common.remote import create_cinder_client
from trove.extensions.mysql import models as mysql_models
from trove.configuration.models import Configuration
from trove.extensions.security_group.models import SecurityGroup
from trove.extensions.security_group.models import SecurityGroupRule
from swiftclient.client import ClientException
from trove.instance import models as inst_models
from trove.instance.models import BuiltInstance
from trove.instance.models import DBInstance
from trove.instance.models import FreshInstance
from trove.instance.tasks import InstanceTasks
from trove.instance.models import InstanceStatus
from trove.instance.models import InstanceServiceStatus
from trove.openstack.common import log as logging
from trove.openstack.common.gettextutils import _
from trove.openstack.common.notifier import api as notifier
from trove.openstack.common import timeutils
import trove.common.remote as remote

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
VOLUME_TIME_OUT = CONF.volume_time_out  # seconds.
DNS_TIME_OUT = CONF.dns_time_out  # seconds.
RESIZE_TIME_OUT = CONF.resize_time_out  # seconds.
REVERT_TIME_OUT = CONF.revert_time_out  # seconds.
HEAT_TIME_OUT = CONF.heat_time_out  # seconds.
USAGE_SLEEP_TIME = CONF.usage_sleep_time  # seconds.
HEAT_STACK_SUCCESSFUL_STATUSES = [('CREATE', 'CREATE_COMPLETE')]
HEAT_RESOURCE_SUCCESSFUL_STATE = 'CREATE_COMPLETE'

use_nova_server_volume = CONF.use_nova_server_volume
use_heat = CONF.use_heat


class NotifyMixin(object):
    """Notification Mixin

    This adds the ability to send usage events to an Instance object.
    """

    def _get_service_id(self, datastore_manager, id_map):
        if datastore_manager in id_map:
            datastore_manager_id = id_map[datastore_manager]
        else:
            datastore_manager_id = cfg.UNKNOWN_SERVICE_ID
            LOG.error("Datastore ID for Manager (%s) is not configured"
                      % datastore_manager)
        return datastore_manager_id

    def send_usage_event(self, event_type, **kwargs):
        event_type = 'trove.instance.%s' % event_type
        publisher_id = CONF.host
        # Grab the instance size from the kwargs or from the nova client
        instance_size = kwargs.pop('instance_size', None)
        flavor = self.nova_client.flavors.get(self.flavor_id)
        server = kwargs.pop('server', None)
        if server is None:
            server = self.nova_client.servers.get(self.server_id)
        az = getattr(server, 'OS-EXT-AZ:availability_zone', None)

        # Default payload
        created_time = timeutils.isotime(self.db_info.created)
        payload = {
            'availability_zone': az,
            'created_at': created_time,
            'name': self.name,
            'instance_id': self.id,
            'instance_name': self.name,
            'instance_size': instance_size or flavor.ram,
            'instance_type': flavor.name,
            'instance_type_id': flavor.id,
            'launched_at': created_time,
            'nova_instance_id': self.server_id,
            'region': CONF.region,
            'state_description': self.status,
            'state': self.status,
            'tenant_id': self.tenant_id,
            'user_id': self.context.user,
        }

        if CONF.trove_volume_support:
            payload.update({
                'volume_size': self.volume_size,
                'nova_volume_id': self.volume_id
            })

        payload['service_id'] = self._get_service_id(
            self.datastore_version.manager, CONF.notification_service_id)

        # Update payload with all other kwargs
        payload.update(kwargs)
        LOG.debug(_('Sending event: %(event_type)s, %(payload)s') %
                  {'event_type': event_type, 'payload': payload})
        notifier.notify(self.context, publisher_id, event_type, 'INFO',
                        payload)


class ConfigurationMixin(object):
    """Configuration Mixin

    Configuration related tasks for instances and resizes.
    """

    def _render_config(self, datastore_manager, flavor, instance_id):
        config = template.SingleInstanceConfigTemplate(
            datastore_manager, flavor, instance_id)
        config.render()
        return config

    def _render_override_config(self, datastore_manager, flavor, instance_id,
                                overrides=None):
        config = template.OverrideConfigTemplate(
            datastore_manager, flavor, instance_id)
        config.render(overrides=overrides)
        return config

    def _render_config_dict(self, datastore_manager, flavor, instance_id):
        config = template.SingleInstanceConfigTemplate(
            datastore_manager, flavor, instance_id)
        ret = config.render_dict()
        LOG.debug(_("the default template dict of mysqld section: %s") % ret)
        return ret


class FreshInstanceTasks(FreshInstance, NotifyMixin, ConfigurationMixin):
    def create_instance(self, flavor, image_id, databases, users,
                        datastore_manager, packages, volume_size,
                        backup_id, availability_zone, root_password, nics,
                        overrides):

        LOG.debug(_("begin create_instance for id: %s") % self.id)
        security_groups = None

        # If security group support is enabled and heat based instance
        # orchestration is disabled, create a security group.
        #
        # Heat based orchestration handles security group(resource)
        # in the template definition.
        if CONF.trove_security_groups_support and not use_heat:
            try:
                security_groups = self._create_secgroup(datastore_manager)
            except Exception as e:
                msg = (_("Error creating security group for instance: %s") %
                       self.id)
                err = inst_models.InstanceTasks.BUILDING_ERROR_SEC_GROUP
                self._log_and_raise(e, msg, err)
            else:
                LOG.debug(_("Successfully created security group for "
                            "instance: %s") % self.id)

        if use_heat:
            volume_info = self._create_server_volume_heat(
                flavor,
                image_id,
                datastore_manager,
                volume_size,
                availability_zone,
                nics)
        elif use_nova_server_volume:
            volume_info = self._create_server_volume(
                flavor['id'],
                image_id,
                security_groups,
                datastore_manager,
                volume_size,
                availability_zone,
                nics)
        else:
            volume_info = self._create_server_volume_individually(
                flavor['id'],
                image_id,
                security_groups,
                datastore_manager,
                volume_size,
                availability_zone,
                nics)

        config = self._render_config(datastore_manager, flavor, self.id)
        config_overrides = self._render_override_config(datastore_manager,
                                                        None,
                                                        self.id,
                                                        overrides=overrides)

        backup_info = None
        if backup_id is not None:
                backup = bkup_models.Backup.get_by_id(self.context, backup_id)
                backup_info = {'id': backup_id,
                               'location': backup.location,
                               'type': backup.backup_type,
                               'checksum': backup.checksum,
                               }
        self._guest_prepare(flavor['ram'], volume_info,
                            packages, databases, users, backup_info,
                            config.config_contents, root_password,
                            config_overrides.config_contents)

        if root_password:
            self.report_root_enabled()

        if not self.db_info.task_status.is_error:
            self.reset_task_status()

        # when DNS is supported, we attempt to add this after the
        # instance is prepared.  Otherwise, if DNS fails, instances
        # end up in a poorer state and there's no tooling around
        # re-sending the prepare call; retrying DNS is much easier.
        try:
            self._create_dns_entry()
        except Exception as e:
            msg = _("Error creating DNS entry for instance: %s") % self.id
            err = inst_models.InstanceTasks.BUILDING_ERROR_DNS
            self._log_and_raise(e, msg, err)
        else:
            LOG.debug(_("Successfully created DNS entry for instance: %s") %
                      self.id)

        # Make sure the service becomes active before sending a usage
        # record to avoid over billing a customer for an instance that
        # fails to build properly.
        try:
            usage_timeout = CONF.get(datastore_manager).usage_timeout
            utils.poll_until(self._service_is_active,
                             sleep_time=USAGE_SLEEP_TIME,
                             time_out=usage_timeout)
            self.send_usage_event('create', instance_size=flavor['ram'])
        except PollTimeOut:
            LOG.error(_("Timeout for service changing to active. "
                      "No usage create-event sent."))
            self.update_statuses_on_time_out()

        except Exception:
            LOG.exception(_("Error during create-event call."))

        LOG.debug(_("end create_instance for id: %s") % self.id)

    def report_root_enabled(self):
        mysql_models.RootHistory.create(self.context, self.id, 'root')

    def update_statuses_on_time_out(self):

        if CONF.update_status_on_fail:
            #Updating service status
            service = InstanceServiceStatus.find_by(instance_id=self.id)
            service.set_status(ServiceStatuses.
                               FAILED_TIMEOUT_GUESTAGENT)
            service.save()
            LOG.error(_("Service status: %(status)s") %
                      {'status': ServiceStatuses.
                       FAILED_TIMEOUT_GUESTAGENT.api_status})
            LOG.error(_("Service error description: %(desc)s") %
                      {'desc': ServiceStatuses.
                       FAILED_TIMEOUT_GUESTAGENT.description})
            #Updating instance status
            db_info = DBInstance.find_by(name=self.name)
            db_info.set_task_status(InstanceTasks.
                                    BUILDING_ERROR_TIMEOUT_GA)
            db_info.save()
            LOG.error(_("Trove instance status: %(action)s") %
                      {'action': InstanceTasks.
                       BUILDING_ERROR_TIMEOUT_GA.action})
            LOG.error(_("Trove instance status description: %(text)s") %
                      {'text': InstanceTasks.
                       BUILDING_ERROR_TIMEOUT_GA.db_text})

    def _service_is_active(self):
        """
        Check that the database guest is active.

        This function is meant to be called with poll_until to check that
        the guest is alive before sending a 'create' message. This prevents
        over billing a customer for a instance that they can never use.

        Returns: boolean if the service is active.
        Raises: TroveError if the service is in a failure state.
        """
        service = InstanceServiceStatus.find_by(instance_id=self.id)
        status = service.get_status()
        if status == rd_instance.ServiceStatuses.RUNNING:
            return True
        elif status not in [rd_instance.ServiceStatuses.NEW,
                            rd_instance.ServiceStatuses.BUILDING]:
            raise TroveError(_("Service not active, status: %s") % status)

        c_id = self.db_info.compute_instance_id
        nova_status = self.nova_client.servers.get(c_id).status
        if nova_status in [InstanceStatus.ERROR,
                           InstanceStatus.FAILED]:
            raise TroveError(_("Server not active, status: %s") % nova_status)
        return False

    def _create_server_volume(self, flavor_id, image_id, security_groups,
                              datastore_manager, volume_size,
                              availability_zone, nics):
        LOG.debug(_("begin _create_server_volume for id: %s") % self.id)
        try:
            files = {"/etc/guest_info": ("[DEFAULT]\n--guest_id="
                                         "%s\n--datastore_manager=%s\n"
                                         "--tenant_id=%s\n" %
                                         (self.id, datastore_manager,
                                          self.tenant_id))}
            name = self.hostname or self.name
            volume_desc = ("mysql volume for %s" % self.id)
            volume_name = ("mysql-%s" % self.id)
            volume_ref = {'size': volume_size, 'name': volume_name,
                          'description': volume_desc}

            server = self.nova_client.servers.create(
                name, image_id, flavor_id,
                files=files, volume=volume_ref,
                security_groups=security_groups,
                availability_zone=availability_zone, nics=nics)
            LOG.debug(_("Created new compute instance %(server_id)s "
                        "for id: %(id)s") %
                      {'server_id': server.id, 'id': self.id})

            server_dict = server._info
            LOG.debug(_("Server response: %s") % server_dict)
            volume_id = None
            for volume in server_dict.get('os:volumes', []):
                volume_id = volume.get('id')

            # Record the server ID and volume ID in case something goes wrong.
            self.update_db(compute_instance_id=server.id, volume_id=volume_id)
        except Exception as e:
            msg = _("Error creating server and volume for "
                    "instance %s") % self.id
            LOG.debug(_("end _create_server_volume for id: %s") % self.id)
            err = inst_models.InstanceTasks.BUILDING_ERROR_SERVER
            self._log_and_raise(e, msg, err)

        device_path = CONF.device_path
        mount_point = CONF.get(datastore_manager).mount_point
        volume_info = {'device_path': device_path, 'mount_point': mount_point}
        LOG.debug(_("end _create_server_volume for id: %s") % self.id)
        return volume_info

    def _create_server_volume_heat(self, flavor, image_id,
                                   datastore_manager,
                                   volume_size, availability_zone, nics):
        LOG.debug(_("begin _create_server_volume_heat for id: %s") % self.id)
        try:
            client = create_heat_client(self.context)

            ifaces, ports = self._build_heat_nics(nics)
            template_obj = template.load_heat_template(datastore_manager)
            heat_template_unicode = template_obj.render(
                volume_support=CONF.trove_volume_support,
                ifaces=ifaces, ports=ports)
            try:
                heat_template = heat_template_unicode.encode('utf-8')
            except UnicodeEncodeError:
                LOG.error(_("heat template ascii encode issue"))
                raise TroveError("heat template ascii encode issue")

            parameters = {"Flavor": flavor["name"],
                          "VolumeSize": volume_size,
                          "InstanceId": self.id,
                          "ImageId": image_id,
                          "DatastoreManager": datastore_manager,
                          "AvailabilityZone": availability_zone,
                          "TenantId": self.tenant_id}
            stack_name = 'trove-%s' % self.id
            client.stacks.create(stack_name=stack_name,
                                 template=heat_template,
                                 parameters=parameters)
            try:
                utils.poll_until(
                    lambda: client.stacks.get(stack_name),
                    lambda stack: stack.stack_status in ['CREATE_COMPLETE',
                                                         'CREATE_FAILED'],
                    sleep_time=USAGE_SLEEP_TIME,
                    time_out=HEAT_TIME_OUT)
            except PollTimeOut:
                LOG.error(_("Timeout during stack status tracing"))
                raise TroveError("Timeout occured in tracking stack status")

            stack = client.stacks.get(stack_name)
            if ((stack.action, stack.stack_status)
                    not in HEAT_STACK_SUCCESSFUL_STATUSES):
                raise TroveError("Heat Stack Create Failed.")

            resource = client.resources.get(stack.id, 'BaseInstance')
            if resource.resource_status != HEAT_RESOURCE_SUCCESSFUL_STATE:
                raise TroveError("Heat Resource Provisioning Failed.")
            instance_id = resource.physical_resource_id

            if CONF.trove_volume_support:
                resource = client.resources.get(stack.id, 'DataVolume')
                if resource.resource_status != HEAT_RESOURCE_SUCCESSFUL_STATE:
                    raise TroveError("Heat Resource Provisioning Failed.")
                volume_id = resource.physical_resource_id
                self.update_db(compute_instance_id=instance_id,
                               volume_id=volume_id)
            else:
                self.update_db(compute_instance_id=instance_id)

        except (TroveError, heat_exceptions.HTTPNotFound) as e:
            msg = _("Error during creating stack for instance %s") % self.id
            LOG.debug(msg)
            err = inst_models.InstanceTasks.BUILDING_ERROR_SERVER
            self._log_and_raise(e, msg, err)

        device_path = CONF.device_path
        mount_point = CONF.get(datastore_manager).mount_point
        volume_info = {'device_path': device_path, 'mount_point': mount_point}

        LOG.debug(_("end _create_server_volume_heat for id: %s") % self.id)
        return volume_info

    def _create_server_volume_individually(self, flavor_id, image_id,
                                           security_groups, datastore_manager,
                                           volume_size,
                                           availability_zone, nics):
        LOG.debug(_("begin _create_server_volume_individually for id: %s") %
                  self.id)
        server = None
        volume_info = self._build_volume_info(datastore_manager,
                                              volume_size=volume_size)
        block_device_mapping = volume_info['block_device']
        try:
            server = self._create_server(flavor_id, image_id, security_groups,
                                         datastore_manager,
                                         block_device_mapping,
                                         availability_zone, nics)
            server_id = server.id
            # Save server ID.
            self.update_db(compute_instance_id=server_id)
        except Exception as e:
            msg = _("Error creating server for instance %s") % self.id
            err = inst_models.InstanceTasks.BUILDING_ERROR_SERVER
            self._log_and_raise(e, msg, err)
        LOG.debug(_("end _create_server_volume_individually for id: %s") %
                  self.id)
        return volume_info

    def _build_volume_info(self, datastore_manager, volume_size=None):
        volume_info = None
        volume_support = CONF.trove_volume_support
        LOG.debug(_("trove volume support = %s") % volume_support)
        if volume_support:
            try:
                volume_info = self._create_volume(
                    volume_size, datastore_manager)
            except Exception as e:
                msg = _("Error provisioning volume for instance: %s") % self.id
                err = inst_models.InstanceTasks.BUILDING_ERROR_VOLUME
                self._log_and_raise(e, msg, err)
        else:
            LOG.debug(_("device_path = %s") % CONF.device_path)
            LOG.debug(_("mount_point = %s") %
                      CONF.get(datastore_manager).mount_point)
            volume_info = {
                'block_device': None,
                'device_path': CONF.device_path,
                'mount_point': CONF.get(datastore_manager).mount_point,
                'volumes': None,
            }
        return volume_info

    def _log_and_raise(self, exc, message, task_status):
        LOG.error(message)
        LOG.error(exc)
        LOG.error(traceback.format_exc())
        self.update_db(task_status=task_status)
        raise TroveError(message=message)

    def _create_volume(self, volume_size, datastore_manager):
        LOG.info("Entering create_volume")
        LOG.debug(_("begin _create_volume for id: %s") % self.id)
        volume_client = create_cinder_client(self.context)
        volume_desc = ("mysql volume for %s" % self.id)
        volume_ref = volume_client.volumes.create(
            volume_size, name="mysql-%s" % self.id, description=volume_desc)

        # Record the volume ID in case something goes wrong.
        self.update_db(volume_id=volume_ref.id)

        utils.poll_until(
            lambda: volume_client.volumes.get(volume_ref.id),
            lambda v_ref: v_ref.status in ['available', 'error'],
            sleep_time=2,
            time_out=VOLUME_TIME_OUT)

        v_ref = volume_client.volumes.get(volume_ref.id)
        if v_ref.status in ['error']:
            raise VolumeCreationFailure()
        LOG.debug(_("end _create_volume for id: %s") % self.id)
        return self._build_volume(v_ref, datastore_manager)

    def _build_volume(self, v_ref, datastore_manager):
        LOG.debug(_("Created volume %s") % v_ref)
        # The mapping is in the format:
        # <id>:[<type>]:[<size(GB)>]:[<delete_on_terminate>]
        # setting the delete_on_terminate instance to true=1
        mapping = "%s:%s:%s:%s" % (v_ref.id, '', v_ref.size, 1)
        bdm = CONF.block_device_mapping
        block_device = {bdm: mapping}
        created_volumes = [{'id': v_ref.id,
                            'size': v_ref.size}]
        LOG.debug("block_device = %s" % block_device)
        LOG.debug("volume = %s" % created_volumes)

        device_path = CONF.device_path
        mount_point = CONF.get(datastore_manager).mount_point
        LOG.debug(_("device_path = %s") % device_path)
        LOG.debug(_("mount_point = %s") % mount_point)

        volume_info = {'block_device': block_device,
                       'device_path': device_path,
                       'mount_point': mount_point,
                       'volumes': created_volumes}
        return volume_info

    def _create_server(self, flavor_id, image_id, security_groups,
                       datastore_manager, block_device_mapping,
                       availability_zone, nics):
        files = {"/etc/guest_info": ("[DEFAULT]\nguest_id=%s\n"
                                     "datastore_manager=%s\n"
                                     "tenant_id=%s\n" %
                                     (self.id, datastore_manager,
                                      self.tenant_id))}
        if os.path.isfile(CONF.get('guest_config')):
            with open(CONF.get('guest_config'), "r") as f:
                files["/etc/trove-guestagent.conf"] = f.read()
        userdata = None
        cloudinit = os.path.join(CONF.get('cloudinit_location'),
                                 "%s.cloudinit" % datastore_manager)
        if os.path.isfile(cloudinit):
            with open(cloudinit, "r") as f:
                userdata = f.read()
        name = self.hostname or self.name
        bdmap = block_device_mapping
        server = self.nova_client.servers.create(
            name, image_id, flavor_id, files=files, userdata=userdata,
            security_groups=security_groups, block_device_mapping=bdmap,
            availability_zone=availability_zone, nics=nics)
        LOG.debug(_("Created new compute instance %(server_id)s "
                    "for id: %(id)s") %
                  {'server_id': server.id, 'id': self.id})
        return server

    def _guest_prepare(self, flavor_ram, volume_info,
                       packages, databases, users, backup_info=None,
                       config_contents=None, root_password=None,
                       overrides=None):
        LOG.info(_("Entering guest_prepare"))
        # Now wait for the response from the create to do additional work
        self.guest.prepare(flavor_ram, packages, databases, users,
                           device_path=volume_info['device_path'],
                           mount_point=volume_info['mount_point'],
                           backup_info=backup_info,
                           config_contents=config_contents,
                           root_password=root_password,
                           overrides=overrides)

    def _create_dns_entry(self):
        LOG.debug(_("%(gt)s: Creating dns entry for instance: %(id)s") %
                  {'gt': greenthread.getcurrent(), 'id': self.id})
        dns_support = CONF.trove_dns_support
        LOG.debug(_("trove dns support = %s") % dns_support)

        if dns_support:
            dns_client = create_dns_client(self.context)

            def get_server():
                c_id = self.db_info.compute_instance_id
                return self.nova_client.servers.get(c_id)

            def ip_is_available(server):
                LOG.info(_("Polling for ip addresses: $%s ") %
                         server.addresses)
                if server.addresses != {}:
                    return True
                elif (server.addresses == {} and
                      server.status != InstanceStatus.ERROR):
                    return False
                elif (server.addresses == {} and
                      server.status == InstanceStatus.ERROR):
                    LOG.error(_("Instance IP not available, "
                                "instance (%(instance)s): "
                                "server had status (%(status)s).") %
                              {'instance': self.id, 'status': server.status})
                    raise TroveError(status=server.status)

            utils.poll_until(get_server, ip_is_available,
                             sleep_time=1, time_out=DNS_TIME_OUT)
            server = self.nova_client.servers.get(
                self.db_info.compute_instance_id)
            self.db_info.addresses = server.addresses
            LOG.info(_("Creating dns entry..."))
            ip = self.dns_ip_address
            if not ip:
                raise TroveError('Error creating DNS. No IP available.')
            dns_client.create_instance_entry(self.id, ip)
        else:
            LOG.debug(_("%(gt)s: DNS not enabled for instance: %(id)s") %
                      {'gt': greenthread.getcurrent(), 'id': self.id})

    def _create_secgroup(self, datastore_manager):
        security_group = SecurityGroup.create_for_instance(
            self.id, self.context)
        tcp_ports = CONF.get(datastore_manager).tcp_ports
        udp_ports = CONF.get(datastore_manager).udp_ports
        self._create_rules(security_group, tcp_ports, 'tcp')
        self._create_rules(security_group, udp_ports, 'udp')
        return [security_group["name"]]

    def _create_rules(self, s_group, ports, protocol):
        err = inst_models.InstanceTasks.BUILDING_ERROR_SEC_GROUP
        err_msg = _("Error creating security group rules."
                    " Invalid port format. "
                    "FromPort = %(from)s, ToPort = %(to)s")

        def set_error_and_raise(port_or_range):
            from_port, to_port = port_or_range
            self.update_db(task_status=err)
            msg = err_msg % {'from': from_port, 'to': to_port}
            raise MalformedSecurityGroupRuleError(message=msg)

        for port_or_range in set(ports):
            try:
                from_, to_ = (None, None)
                from_, to_ = utils.gen_ports(port_or_range)
                cidr = CONF.trove_security_group_rule_cidr
                SecurityGroupRule.create_sec_group_rule(
                    s_group, protocol, int(from_), int(to_),
                    cidr, self.context)
            except (ValueError, TroveError):
                set_error_and_raise([from_, to_])

    def _build_heat_nics(self, nics):
        ifaces = []
        ports = []
        if nics:
            for idx, nic in enumerate(nics):
                iface_id = nic.get('port-id')
                if iface_id:
                    ifaces.append(iface_id)
                    continue
                net_id = nic.get('net-id')
                if net_id:
                    port = {}
                    port['name'] = "Port%s" % idx
                    port['net_id'] = net_id
                    fixed_ip = nic.get('v4-fixed-ip')
                    if fixed_ip:
                        port['fixed_ip'] = fixed_ip
                    ports.append(port)
                    ifaces.append("{Ref: Port%s}" % idx)
        return ifaces, ports


class BuiltInstanceTasks(BuiltInstance, NotifyMixin, ConfigurationMixin):
    """
    Performs the various asynchronous instance related tasks.
    """

    def _delete_resources(self, deleted_at):
        LOG.debug(_("begin _delete_resources for id: %s") % self.id)
        server_id = self.db_info.compute_instance_id
        old_server = self.nova_client.servers.get(server_id)
        try:
            if use_heat:
                # Delete the server via heat
                heatclient = create_heat_client(self.context)
                name = 'trove-%s' % self.id
                heatclient.stacks.delete(name)
            else:
                self.server.delete()
        except Exception as ex:
            LOG.exception(_("Error during delete compute server %s")
                          % self.server.id)
        try:
            dns_support = CONF.trove_dns_support
            LOG.debug(_("trove dns support = %s") % dns_support)
            if dns_support:
                dns_api = create_dns_client(self.context)
                dns_api.delete_instance_entry(instance_id=self.db_info.id)
        except Exception as ex:
            LOG.exception(_("Error during dns entry of instance %(id)s: "
                            "%(ex)s") % {'id': self.db_info.id, 'ex': ex})

            # Poll until the server is gone.
        def server_is_finished():
            try:
                server = self.nova_client.servers.get(server_id)
                if not self.server_status_matches(['SHUTDOWN', 'ACTIVE'],
                                                  server=server):
                    LOG.error(_("Server %(server_id)s got into ERROR status "
                                "during delete of instance %(instance_id)s!") %
                              {'server_id': server.id, 'instance_id': self.id})
                return False
            except nova_exceptions.NotFound:
                return True

        try:
            utils.poll_until(server_is_finished, sleep_time=2,
                             time_out=CONF.server_delete_time_out)
        except PollTimeOut:
            LOG.exception(_("Timout during nova server delete of server: %s") %
                          server_id)
        self.send_usage_event('delete',
                              deleted_at=timeutils.isotime(deleted_at),
                              server=old_server)
        LOG.debug(_("end _delete_resources for id: %s") % self.id)

    def server_status_matches(self, expected_status, server=None):
        if not server:
            server = self.server
        return server.status.upper() in (
            status.upper() for status in expected_status)

    def resize_volume(self, new_size):
        LOG.debug(_("begin resize_volume for instance: %s") % self.id)
        action = ResizeVolumeAction(self, self.volume_size, new_size)
        action.execute()
        LOG.debug(_("end resize_volume for instance: %s") % self.id)

    def resize_flavor(self, old_flavor, new_flavor):
        action = ResizeAction(self, old_flavor, new_flavor)
        action.execute()

    def migrate(self, host):
        LOG.debug(_("Calling migrate with host(%s)...") % host)
        action = MigrateAction(self, host)
        action.execute()

    def create_backup(self, backup_info):
        LOG.debug(_("Calling create_backup  %s ") % self.id)
        self.guest.create_backup(backup_info)

    def reboot(self):
        try:
            LOG.debug(_("Instance %s calling stop_db...") % self.id)
            self.guest.stop_db()
            LOG.debug(_("Rebooting instance %s") % self.id)
            self.server.reboot()

            # Poll nova until instance is active
            reboot_time_out = CONF.reboot_time_out

            def update_server_info():
                self.refresh_compute_server_info()
                return self.server_status_matches(['ACTIVE'])

            utils.poll_until(
                update_server_info,
                sleep_time=2,
                time_out=reboot_time_out)

            # Set the status to PAUSED. The guest agent will reset the status
            # when the reboot completes and MySQL is running.
            self.set_datastore_status_to_paused()
            LOG.debug(_("Successfully rebooted instance %s") % self.id)
        except Exception as e:
            LOG.error(_("Failed to reboot instance %(id)s: %(e)s") %
                      {'id': self.id, 'e': str(e)})
        finally:
            LOG.debug(_("Rebooting FINALLY  %s") % self.id)
            self.reset_task_status()

    def restart(self):
        LOG.debug(_("Restarting datastore on instance %s ") % self.id)
        try:
            self.guest.restart()
            LOG.debug(_("Restarting datastore successful  %s ") % self.id)
        except GuestError:
            LOG.error(_("Failure to restart datastore for instance %s.") %
                      self.id)
        finally:
            LOG.debug(_("Restarting complete on instance  %s ") % self.id)
            self.reset_task_status()

    def update_overrides(self, overrides, remove=False):
        LOG.debug(_("Updating configuration overrides on instance %s")
                  % self.id)
        LOG.debug(_("overrides: %s") % overrides)
        LOG.debug(_("self.ds_version: %s") % self.ds_version.__dict__)
        # todo(cp16net) How do we know what datastore type we have?
        need_restart = do_configs_require_restart(
            overrides, datastore_manager=self.ds_version.manager)
        LOG.debug(_("do we need a restart?: %s") % need_restart)
        if need_restart:
            status = inst_models.InstanceTasks.RESTART_REQUIRED
            self.update_db(task_status=status)

        config_overrides = self._render_override_config(
            self.ds_version.manager,
            None,
            self.id,
            overrides=overrides)
        try:
            self.guest.update_overrides(config_overrides.config_contents,
                                        remove=remove)
            self.guest.apply_overrides(overrides)
            LOG.debug(_("Configuration overrides update successful."))
        except GuestError:
            LOG.error(_("Failed to update configuration overrides."))

    def unassign_configuration(self, flavor, configuration_id):
        LOG.debug(_("Unassigning the configuration from the instance %s")
                  % self.id)
        LOG.debug(_("Unassigning the configuration id %s")
                  % self.configuration.id)

        def _find_item(items, item_name):
            LOG.debug(_("items: %s") % items)
            LOG.debug(_("item_name: %s") % item_name)
            # find the item in the list
            for i in items:
                if i[0] == item_name:
                    return i

        def _convert_value(value):
            # split the value and the size e.g. 512M=['512','M']
            pattern = re.compile('(\d+)(\w+)')
            split = pattern.findall(value)
            if len(split) < 2:
                return value
            digits, size = split
            conversions = {
                'K': 1024,
                'M': 1024 ** 2,
                'G': 1024 ** 3,
            }
            return str(int(digits) * conversions[size])

        default_config = self._render_config_dict(self.ds_version.manager,
                                                  flavor,
                                                  self.id)
        args = {
            "ds_manager": self.ds_version.manager,
            "config": default_config,
        }
        LOG.debug(_("default %(ds_manager)s section: %(config)s") % args)
        LOG.debug(_("self.configuration: %s") % self.configuration.__dict__)

        overrides = {}
        config_items = Configuration.load_items(self.context, configuration_id)
        for item in config_items:
            LOG.debug(_("finding item(%s)") % item.__dict__)
            try:
                key, val = _find_item(default_config, item.configuration_key)
            except TypeError:
                val = None
                restart_required = inst_models.InstanceTasks.RESTART_REQUIRED
                self.update_db(task_status=restart_required)
            if val:
                overrides[item.configuration_key] = _convert_value(val)
        LOG.debug(_("setting the default variables in dict: %s") % overrides)
        self.update_overrides(overrides, remove=True)
        self.update_db(configuration_id=None)

    def refresh_compute_server_info(self):
        """Refreshes the compute server field."""
        server = self.nova_client.servers.get(self.server.id)
        self.server = server

    def _refresh_datastore_status(self):
        """
        Gets the latest instance service status from datastore and updates
        the reference on this BuiltInstanceTask reference
        """
        self.datastore_status = InstanceServiceStatus.find_by(
            instance_id=self.id)

    def set_datastore_status_to_paused(self):
        """
        Updates the InstanceServiceStatus for this BuiltInstance to PAUSED.
        This does not change the reference for this BuiltInstanceTask
        """
        datastore_status = InstanceServiceStatus.find_by(instance_id=self.id)
        datastore_status.status = rd_instance.ServiceStatuses.PAUSED
        datastore_status.save()


class BackupTasks(object):
    @classmethod
    def _parse_manifest(cls, manifest):
        # manifest is in the format 'container/prefix'
        # where prefix can be 'path' or 'lots/of/paths'
        try:
            container_index = manifest.index('/')
            prefix_index = container_index + 1
        except ValueError:
            return None, None
        container = manifest[:container_index]
        prefix = manifest[prefix_index:]
        return container, prefix

    @classmethod
    def delete_files_from_swift(cls, context, filename):
        container = CONF.backup_swift_container
        client = remote.create_swift_client(context)
        obj = client.head_object(container, filename)
        manifest = obj.get('x-object-manifest', '')
        cont, prefix = cls._parse_manifest(manifest)
        if all([cont, prefix]):
            # This is a manifest file, first delete all segments.
            LOG.info(_("Deleting files with prefix: %(cont)s/%(prefix)s") %
                     {'cont': cont, 'prefix': prefix})
            # list files from container/prefix specified by manifest
            headers, segments = client.get_container(cont, prefix=prefix)
            LOG.debug(headers)
            for segment in segments:
                name = segment.get('name')
                if name:
                    LOG.info(_("Deleting file: %(cont)s/%(name)s") %
                             {'cont': cont, 'name': name})
                    client.delete_object(cont, name)
        # Delete the manifest file
        LOG.info(_("Deleting file: %(cont)s/%(filename)s") %
                 {'cont': cont, 'filename': filename})
        client.delete_object(container, filename)

    @classmethod
    def delete_backup(cls, context, backup_id):
        #delete backup from swift
        backup = bkup_models.Backup.get_by_id(context, backup_id)
        try:
            filename = backup.filename
            if filename:
                BackupTasks.delete_files_from_swift(context, filename)
        except ValueError:
            backup.delete()
        except ClientException as e:
            if e.http_status == 404:
                # Backup already deleted in swift
                backup.delete()
            else:
                LOG.exception(_("Exception deleting from swift. "
                                "Details: %s") % e)
                backup.state = bkup_models.BackupState.DELETE_FAILED
                backup.save()
                raise TroveError("Failed to delete swift objects")
        else:
            backup.delete()


class ResizeVolumeAction(ConfigurationMixin):
    """Performs volume resize action."""

    def __init__(self, instance, old_size, new_size):
        self.instance = instance
        self.old_size = int(old_size)
        self.new_size = int(new_size)

    def get_mount_point(self):
        mount_point = CONF.get(
            self.instance.datastore_version.manager).mount_point
        return mount_point

    def _fail(self, orig_func):
        LOG.exception(_("%(func)s encountered an error when attempting to "
                      "resize the volume for instance %(id)s. Setting service "
                      "status to failed.") % {'func': orig_func.__name__,
                      'id': self.instance.id})
        service = InstanceServiceStatus.find_by(instance_id=self.instance.id)
        service.set_status(ServiceStatuses.FAILED)
        service.save()

    def _recover_restart(self, orig_func):
        LOG.exception(_("%(func)s encountered an error when attempting to "
                      "resize the volume for instance %(id)s. Trying to "
                      "recover by restarting the guest.") % {
                      'func': orig_func.__name__,
                      'id': self.instance.id})
        self.instance.restart()

    def _recover_mount_restart(self, orig_func):
        LOG.exception(_("%(func)s encountered an error when attempting to "
                      "resize the volume for instance %(id)s. Trying to "
                      "recover by mounting the volume and then restarting the "
                      "guest.") % {'func': orig_func.__name__,
                      'id': self.instance.id})
        self._mount_volume()
        self.instance.restart()

    def _recover_full(self, orig_func):
        LOG.exception(_("%(func)s encountered an error when attempting to "
                      "resize the volume for instance %(id)s. Trying to "
                      "recover by attaching and mounting the volume and then "
                      "restarting the guest.") % {'func': orig_func.__name__,
                      'id': self.instance.id})
        self._attach_volume()
        self._mount_volume()
        self.instance.restart()

    def _stop_db(self):
        LOG.debug(_("Instance %s calling stop_db.") % self.instance.id)
        self.instance.guest.stop_db()

    @try_recover
    def _unmount_volume(self):
        LOG.debug(_("Unmounting the volume on instance %(id)s") % {
                  'id': self.instance.id})
        mount_point = self.get_mount_point()
        self.instance.guest.unmount_volume(device_path=CONF.device_path,
                                           mount_point=mount_point)
        LOG.debug(_("Successfully unmounted the volume %(vol_id)s for "
                  "instance %(id)s") % {'vol_id': self.instance.volume_id,
                  'id': self.instance.id})

    @try_recover
    def _detach_volume(self):
        LOG.debug(_("Detach volume %(vol_id)s from instance %(id)s") % {
                  'vol_id': self.instance.volume_id,
                  'id': self.instance.id})
        self.instance.volume_client.volumes.detach(self.instance.volume_id)

        def volume_available():
            volume = self.instance.volume_client.volumes.get(
                self.instance.volume_id)
            return volume.status == 'available'
        utils.poll_until(volume_available,
                         sleep_time=2,
                         time_out=CONF.volume_time_out)

        LOG.debug(_("Successfully detached volume %(vol_id)s from instance "
                    "%(id)s") % {'vol_id': self.instance.volume_id,
                                 'id': self.instance.id})

    @try_recover
    def _attach_volume(self):
        LOG.debug(_("Attach volume %(vol_id)s to instance %(id)s at "
                  "%(dev)s") % {'vol_id': self.instance.volume_id,
                  'id': self.instance.id, 'dev': CONF.device_path})
        self.instance.volume_client.volumes.attach(self.instance.volume_id,
                                                   self.instance.server.id,
                                                   CONF.device_path)

        def volume_in_use():
            volume = self.instance.volume_client.volumes.get(
                self.instance.volume_id)
            return volume.status == 'in-use'
        utils.poll_until(volume_in_use,
                         sleep_time=2,
                         time_out=CONF.volume_time_out)

        LOG.debug(_("Successfully attached volume %(vol_id)s to instance "
                  "%(id)s") % {'vol_id': self.instance.volume_id,
                  'id': self.instance.id})

    @try_recover
    def _resize_fs(self):
        LOG.debug(_("Resizing the filesystem for instance %(id)s") % {
                  'id': self.instance.id})
        mount_point = self.get_mount_point()
        self.instance.guest.resize_fs(device_path=CONF.device_path,
                                      mount_point=mount_point)
        LOG.debug(_("Successfully resized volume %(vol_id)s filesystem for "
                  "instance %(id)s") % {'vol_id': self.instance.volume_id,
                  'id': self.instance.id})

    @try_recover
    def _mount_volume(self):
        LOG.debug(_("Mount the volume on instance %(id)s") % {
                  'id': self.instance.id})
        mount_point = self.get_mount_point()
        self.instance.guest.mount_volume(device_path=CONF.device_path,
                                         mount_point=mount_point)
        LOG.debug(_("Successfully mounted the volume %(vol_id)s on instance "
                  "%(id)s") % {'vol_id': self.instance.volume_id,
                  'id': self.instance.id})

    @try_recover
    def _extend(self):
        LOG.debug(_("Extending volume %(vol_id)s for instance %(id)s to "
                  "size %(size)s") % {'vol_id': self.instance.volume_id,
                  'id': self.instance.id, 'size': self.new_size})
        self.instance.volume_client.volumes.extend(self.instance.volume_id,
                                                   self.new_size)
        LOG.debug(_("Successfully extended the volume %(vol_id)s for instance "
                  "%(id)s") % {'vol_id': self.instance.volume_id,
                  'id': self.instance.id})

    def _verify_extend(self):
        try:
            volume = self.instance.volume_client.volumes.get(
                self.instance.volume_id)
            if not volume:
                msg = (_('Failed to get volume %(vol_id)s') % {
                       'vol_id': self.instance.volume_id})
                raise cinder_exceptions.ClientException(msg)

            def volume_is_new_size():
                volume = self.instance.volume_client.volumes.get(
                    self.instance.volume_id)
                return volume.size == self.new_size
            utils.poll_until(volume_is_new_size,
                             sleep_time=2,
                             time_out=CONF.volume_time_out)

            self.instance.update_db(volume_size=self.new_size)
        except PollTimeOut:
            LOG.exception(_("Timeout trying to extend the volume %(vol_id)s "
                          "for instance %(id)s") % {
                          'vol_id': self.instance.volume_id,
                          'id': self.instance.id})
            volume = self.instance.volume_client.volumes.get(
                self.instance.volume_id)
            if volume.status == 'extending':
                self._fail(self._verify_extend)
            elif volume.size != self.new_size:
                self.instance.update_db(volume_size=volume.size)
                self._recover_full(self._verify_extend)
            raise
        except Exception:
            LOG.exception(_("Error encountered trying to verify extend for "
                          "the volume %(vol_id)s for instance %(id)s") % {
                          'vol_id': self.instance.volume_id,
                          'id': self.instance.id})
            self._recover_full(self._verify_extend)
            raise

    def _resize_active_volume(self):
        LOG.debug(_("begin _resize_active_volume for id: %(id)s") % {
                  'id': self.instance.id})
        self._stop_db()
        self._unmount_volume(recover_func=self._recover_restart)
        self._detach_volume(recover_func=self._recover_mount_restart)
        self._extend(recover_func=self._recover_full)
        self._verify_extend()
        # if anything fails after this point, recovery is futile
        self._attach_volume(recover_func=self._fail)
        self._resize_fs(recover_func=self._fail)
        self._mount_volume(recover_func=self._fail)
        self.instance.restart()
        LOG.debug(_("end _resize_active_volume for id: %(id)s") % {
                  'id': self.instance.id})

    def execute(self):
        LOG.debug(_("%(gt)s: Resizing instance %(id)s volume for server "
                  "%(server_id)s from %(old_volume_size)s to "
                  "%(new_size)r GB") % {'gt': greenthread.getcurrent(),
                  'id': self.instance.id,
                  'server_id': self.instance.server.id,
                  'old_volume_size': self.old_size,
                  'new_size': self.new_size})

        if self.instance.server.status == InstanceStatus.ACTIVE:
            self._resize_active_volume()
            self.instance.reset_task_status()
            # send usage event for size reported by cinder
            volume = self.instance.volume_client.volumes.get(
                self.instance.volume_id)
            launched_time = timeutils.isotime(self.instance.updated)
            modified_time = timeutils.isotime(self.instance.updated)
            self.instance.send_usage_event('modify_volume',
                                           old_volume_size=self.old_size,
                                           launched_at=launched_time,
                                           modify_at=modified_time,
                                           volume_size=volume.size)
        else:
            self.instance.reset_task_status()
            msg = _("Volume resize failed for instance %(id)s. The instance "
                    "must be in state %(state)s not %(inst_state)s.") % {
                        'id': self.instance.id,
                        'state': InstanceStatus.ACTIVE,
                        'inst_state': self.instance.server.status}
            raise TroveError(msg)


class ResizeActionBase(ConfigurationMixin):
    """Base class for executing a resize action."""

    def __init__(self, instance):
        """
        Creates a new resize action for a given instance
        :param instance: reference to existing instance that will be resized
        :type instance: trove.taskmanager.models.BuiltInstanceTasks
        """
        self.instance = instance

    def _assert_guest_is_ok(self):
        # The guest will never set the status to PAUSED.
        self.instance.set_datastore_status_to_paused()
        # Now we wait until it sets it to anything at all,
        # so we know it's alive.
        utils.poll_until(
            self._guest_is_awake,
            sleep_time=2,
            time_out=RESIZE_TIME_OUT)

    def _assert_nova_status_is_ok(self):
        # Make sure Nova thinks things went well.
        if not self.instance.server_status_matches(["VERIFY_RESIZE"]):
            msg = "Migration failed! status=%(act_status)s and " \
                  "not %(exp_status)s" % {
                      "act_status": self.instance.server.status,
                      "exp_status": 'VERIFY_RESIZE'}
            raise TroveError(msg)

    def _assert_datastore_is_ok(self):
        # Tell the guest to turn on datastore, and ensure the status becomes
        # RUNNING.
        self._start_datastore()
        utils.poll_until(
            self._datastore_is_online,
            sleep_time=2,
            time_out=RESIZE_TIME_OUT)

    def _assert_datastore_is_offline(self):
        # Tell the guest to turn off MySQL, and ensure the status becomes
        # SHUTDOWN.
        self.instance.guest.stop_db(do_not_start_on_reboot=True)
        utils.poll_until(
            self._datastore_is_offline,
            sleep_time=2,
            time_out=RESIZE_TIME_OUT)

    def _assert_processes_are_ok(self):
        """Checks the procs; if anything is wrong, reverts the operation."""
        # Tell the guest to turn back on, and make sure it can start.
        self._assert_guest_is_ok()
        LOG.debug(_("Nova guest is ok."))
        self._assert_datastore_is_ok()
        LOG.debug(_("Datastore is ok."))

    def _confirm_nova_action(self):
        LOG.debug(_("Instance %s calling Compute confirm resize...")
                  % self.instance.id)
        self.instance.server.confirm_resize()

    def _datastore_is_online(self):
        self.instance._refresh_datastore_status()
        return self.instance.is_datastore_running

    def _datastore_is_offline(self):
        self.instance._refresh_datastore_status()
        return (self.instance.datastore_status_matches(
                rd_instance.ServiceStatuses.SHUTDOWN))

    def _revert_nova_action(self):
        LOG.debug(_("Instance %s calling Compute revert resize...")
                  % self.instance.id)
        self.instance.server.revert_resize()

    def execute(self):
        """Initiates the action."""
        try:
            LOG.debug(_("Instance %s calling stop_db...")
                      % self.instance.id)
            self._assert_datastore_is_offline()
            self._perform_nova_action()
        finally:
            if self.instance.db_info.task_status != (
                    inst_models.InstanceTasks.NONE):
                self.instance.reset_task_status()

    def _guest_is_awake(self):
        self.instance._refresh_datastore_status()
        return not self.instance.datastore_status_matches(
            rd_instance.ServiceStatuses.PAUSED)

    def _perform_nova_action(self):
        """Calls Nova to resize or migrate an instance, and confirms."""
        LOG.debug(_("begin resize method _perform_nova_action instance: %s") %
                  self.instance.id)
        need_to_revert = False
        try:
            LOG.debug(_("Initiating nova action"))
            self._initiate_nova_action()
            LOG.debug(_("Waiting for nova action"))
            self._wait_for_nova_action()
            LOG.debug(_("Asserting nova status is ok"))
            self._assert_nova_status_is_ok()
            need_to_revert = True
            LOG.debug(_("* * * REVERT BARRIER PASSED * * *"))
            LOG.debug(_("Asserting nova action success"))
            self._assert_nova_action_was_successful()
            LOG.debug(_("Asserting processes are OK"))
            self._assert_processes_are_ok()
            LOG.debug(_("Confirming nova action"))
            self._confirm_nova_action()
        except Exception as ex:
            LOG.exception(_("Exception during nova action."))
            if need_to_revert:
                LOG.error(_("Reverting action for instance %s") %
                          self.instance.id)
                self._revert_nova_action()
                self._wait_for_revert_nova_action()

            if self.instance.server_status_matches(['ACTIVE']):
                LOG.error(_("Restarting datastore."))
                self.instance.guest.restart()
            else:
                LOG.error(_("Cannot restart datastore because "
                            "Nova server status is not ACTIVE"))

            LOG.error(_("Error resizing instance %s.") % self.instance.id)
            raise ex

        LOG.debug(_("Recording success"))
        self._record_action_success()
        LOG.debug(_("end resize method _perform_nova_action instance: %s") %
                  self.instance.id)

    def _wait_for_nova_action(self):
        # Wait for the flavor to change.
        def update_server_info():
            self.instance.refresh_compute_server_info()
            return not self.instance.server_status_matches(['RESIZE'])

        utils.poll_until(
            update_server_info,
            sleep_time=2,
            time_out=RESIZE_TIME_OUT)

    def _wait_for_revert_nova_action(self):
        # Wait for the server to return to ACTIVE after revert.
        def update_server_info():
            self.instance.refresh_compute_server_info()
            return self.instance.server_status_matches(['ACTIVE'])

        utils.poll_until(
            update_server_info,
            sleep_time=2,
            time_out=REVERT_TIME_OUT)


class ResizeAction(ResizeActionBase):
    def __init__(self, instance, old_flavor, new_flavor):
        """
        :type instance: trove.taskmanager.models.BuiltInstanceTasks
        :type old_flavor: dict
        :type new_flavor: dict
        """
        super(ResizeAction, self).__init__(instance)
        self.old_flavor = old_flavor
        self.new_flavor = new_flavor
        self.new_flavor_id = new_flavor['id']

    def _assert_nova_action_was_successful(self):
        # Do check to make sure the status and flavor id are correct.
        if str(self.instance.server.flavor['id']) != str(self.new_flavor_id):
            msg = "Assertion failed! flavor_id=%s and not %s" \
                  % (self.instance.server.flavor['id'], self.new_flavor_id)
            raise TroveError(msg)

    def _initiate_nova_action(self):
        self.instance.server.resize(self.new_flavor_id)

    def _revert_nova_action(self):
        LOG.debug(_("Instance %s calling Compute revert resize...")
                  % self.instance.id)
        LOG.debug(_("Repairing config."))
        try:
            config = self._render_config(
                self.instance.datastore_version.manager,
                self.old_flavor,
                self.instance.id
            )
            config = {'config_contents': config.config_contents}
            self.instance.guest.reset_configuration(config)
        except GuestTimeout:
            LOG.exception(_("Error sending reset_configuration call."))
        LOG.debug(_("Reverting resize."))
        super(ResizeAction, self)._revert_nova_action()

    def _record_action_success(self):
        LOG.debug(_("Updating instance %(id)s to flavor_id %(flavor_id)s.")
                  % {'id': self.instance.id, 'flavor_id': self.new_flavor_id})
        self.instance.update_db(flavor_id=self.new_flavor_id,
                                task_status=inst_models.InstanceTasks.NONE)
        self.instance.send_usage_event(
            'modify_flavor',
            old_instance_size=self.old_flavor['ram'],
            instance_size=self.new_flavor['ram'],
            launched_at=timeutils.isotime(self.instance.updated),
            modify_at=timeutils.isotime(self.instance.updated),
            server=self.instance.server)

    def _start_datastore(self):
        config = self._render_config(self.instance.datastore_version.manager,
                                     self.new_flavor, self.instance.id)
        self.instance.guest.start_db_with_conf_changes(config.config_contents)


class MigrateAction(ResizeActionBase):
    def __init__(self, instance, host=None):
        super(MigrateAction, self).__init__(instance)
        self.instance = instance
        self.host = host

    def _assert_nova_action_was_successful(self):
        LOG.debug(_("Currently no assertions for a Migrate Action"))

    def _initiate_nova_action(self):
        LOG.debug(_("Migrating instance %s without flavor change ...")
                  % self.instance.id)
        LOG.debug(_("Forcing migration to host(%s)") % self.host)
        self.instance.server.migrate(force_host=self.host)

    def _record_action_success(self):
        LOG.debug(_("Successfully finished Migration to "
                    "%(hostname)s: %(id)s") %
                  {'hostname': self.instance.hostname,
                   'id': self.instance.id})

    def _start_datastore(self):
        self.instance.guest.restart()
