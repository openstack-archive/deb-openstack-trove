# Copyright 2011 OpenStack Foundation
# Copyright 2014 Rackspace Hosting
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
"""Routines for configuring Trove."""

import os.path

from oslo.config import cfg
import trove


UNKNOWN_SERVICE_ID = 'unknown-service-id-error'

path_opts = [
    cfg.StrOpt('pybasedir',
               default=os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                    '../')),
               help='Directory where the Trove python module is installed.'),
]

common_opts = [
    cfg.StrOpt('sql_connection',
               default='sqlite:///trove_test.sqlite',
               help='SQL Connection.',
               secret=True),
    cfg.IntOpt('sql_idle_timeout', default=3600,
               help="Idle time (in seconds) after which the connection to the "
                    "database is reestablished. Some databases will drop "
                    "connections after a specific amount of idle time. "
                    "Setting sql_idle_timeout to a lower value than this will "
                    "ensure that a reconnect occurs before the database can "
                    "drop the connection."),
    cfg.BoolOpt('sql_query_log', default=False,
                help='Write all SQL queries to a log.'),
    cfg.StrOpt('bind_host', default='0.0.0.0',
               help='IP address the API server will listen on.'),
    cfg.IntOpt('bind_port', default=8779,
               help='Port the API server will listen on.'),
    cfg.StrOpt('api_paste_config', default="api-paste.ini",
               help='File name for the paste.deploy config for trove-api.'),
    cfg.BoolOpt('trove_volume_support', default=True,
                help='Whether to provision a Cinder volume for datadir.'),
    cfg.ListOpt('admin_roles', default=['admin'],
                help='Roles to add to an admin user.'),
    cfg.BoolOpt('update_status_on_fail', default=True,
                help='Set the service and instance task statuses to ERROR '
                     'when an instance fails to become active within the '
                     'configured usage_timeout.'),
    cfg.StrOpt('os_region_name', default='RegionOne',
               help='Region name of this node. Used when searching catalog.'),
    cfg.StrOpt('nova_compute_url', help='URL without the tenant segment.'),
    cfg.StrOpt('nova_compute_service_type', default='compute',
               help='Service type to use when searching catalog.'),
    cfg.StrOpt('nova_compute_endpoint_type', default='publicURL',
               help='Service endpoint type to use when searching catalog.'),
    cfg.StrOpt('neutron_url', help='URL without the tenant segment.'),
    cfg.StrOpt('neutron_service_type', default='network',
               help='Service type to use when searching catalog.'),
    cfg.StrOpt('neutron_endpoint_type', default='publicURL',
               help='Service endpoint type to use when searching catalog.'),
    cfg.StrOpt('cinder_url', help='URL without the tenant segment.'),
    cfg.StrOpt('cinder_service_type', default='volumev2',
               help='Service type to use when searching catalog.'),
    cfg.StrOpt('cinder_endpoint_type', default='publicURL',
               help='Service endpoint type to use when searching catalog.'),
    cfg.StrOpt('heat_url', help='URL without the tenant segment.'),
    cfg.StrOpt('heat_service_type', default='orchestration',
               help='Service type to use when searching catalog.'),
    cfg.StrOpt('heat_endpoint_type', default='publicURL',
               help='Service endpoint type to use when searching catalog.'),
    cfg.StrOpt('swift_url', help='URL ending in AUTH_.'),
    cfg.StrOpt('swift_service_type', default='object-store',
               help='Service type to use when searching catalog.'),
    cfg.StrOpt('swift_endpoint_type', default='publicURL',
               help='Service endpoint type to use when searching catalog.'),
    cfg.StrOpt('trove_auth_url', default='http://0.0.0.0:5000/v2.0',
               help='Trove authentication URL.'),
    cfg.StrOpt('host', default='0.0.0.0',
               help='Host to listen for RPC messages.'),
    cfg.IntOpt('report_interval', default=10,
               help='The interval (in seconds) which periodic tasks are run.'),
    cfg.BoolOpt('trove_dns_support', default=False,
                help='Whether Trove should add DNS entries on create '
                     '(using Designate DNSaaS).'),
    cfg.StrOpt('db_api_implementation', default='trove.db.sqlalchemy.api',
               help='API Implementation for Trove database access.'),
    cfg.StrOpt('dns_driver', default='trove.dns.driver.DnsDriver',
               help='Driver for DNSaaS.'),
    cfg.StrOpt('dns_instance_entry_factory',
               default='trove.dns.driver.DnsInstanceEntryFactory',
               help='Factory for adding DNS entries.'),
    cfg.StrOpt('dns_hostname', default="",
               help='Hostname used for adding DNS entries.'),
    cfg.StrOpt('dns_account_id', default="",
               help='Tenant ID for DNSaaS.'),
    cfg.StrOpt('dns_endpoint_url', default="0.0.0.0",
               help='Endpoint URL for DNSaaS.'),
    cfg.StrOpt('dns_service_type', default="",
               help='Service Type for DNSaaS.'),
    cfg.StrOpt('dns_region', default="",
               help='Region name for DNSaaS.'),
    cfg.StrOpt('dns_auth_url', default="",
               help='Authentication URL for DNSaaS.'),
    cfg.StrOpt('dns_domain_name', default="",
               help='Domain name used for adding DNS entries.'),
    cfg.StrOpt('dns_username', default="", secret=True,
               help='Username for DNSaaS.'),
    cfg.StrOpt('dns_passkey', default="", secret=True,
               help='Passkey for DNSaaS.'),
    cfg.StrOpt('dns_management_base_url', default="",
               help='Management URL for DNSaaS.'),
    cfg.IntOpt('dns_ttl', default=300,
               help='Time (in seconds) before a refresh of DNS information '
                    'occurs.'),
    cfg.StrOpt('dns_domain_id', default="",
               help='Domain ID used for adding DNS entries.'),
    cfg.IntOpt('users_page_size', default=20,
               help='Page size for listing users.'),
    cfg.IntOpt('databases_page_size', default=20,
               help='Page size for listing databases.'),
    cfg.IntOpt('instances_page_size', default=20,
               help='Page size for listing instances.'),
    cfg.IntOpt('clusters_page_size', default=20,
               help='Page size for listing clusters.'),
    cfg.IntOpt('backups_page_size', default=20,
               help='Page size for listing backups.'),
    cfg.IntOpt('configurations_page_size', default=20,
               help='Page size for listing configurations.'),
    cfg.ListOpt('ignore_users', default=['os_admin', 'root'],
                help='Users to exclude when listing users.'),
    cfg.ListOpt('ignore_dbs',
                default=['lost+found', 'mysql', 'information_schema'],
                help='Databases to exclude when listing databases.'),
    cfg.IntOpt('agent_call_low_timeout', default=5,
               help="Maximum time (in seconds) to wait for Guest Agent 'quick'"
                    "requests (such as retrieving a list of users or "
                    "databases)."),
    cfg.IntOpt('agent_call_high_timeout', default=60,
               help="Maximum time (in seconds) to wait for Guest Agent 'slow' "
                    "requests (such as restarting the database)."),
    cfg.IntOpt('agent_replication_snapshot_timeout', default=36000,
               help='Maximum time (in seconds) to wait for taking a Guest '
                    'Agent replication snapshot.'),
    # The guest_id opt definition must match the one in cmd/guest.py
    cfg.StrOpt('guest_id', default=None, help="ID of the Guest Instance."),
    cfg.IntOpt('state_change_wait_time', default=3 * 60,
               help='Maximum time (in seconds) to wait for a state change.'),
    cfg.IntOpt('agent_heartbeat_time', default=10,
               help='Maximum time (in seconds) for the Guest Agent to reply '
                    'to a heartbeat request.'),
    cfg.IntOpt('num_tries', default=3,
               help='Number of times to check if a volume exists.'),
    cfg.StrOpt('volume_fstype', default='ext3',
               help='File system type used to format a volume.'),
    cfg.StrOpt('cinder_volume_type', default=None,
               help='Volume type to use when provisioning a Cinder volume.'),
    cfg.StrOpt('format_options', default='-m 5',
               help='Options to use when formatting a volume.'),
    cfg.IntOpt('volume_format_timeout', default=120,
               help='Maximum time (in seconds) to wait for a volume format.'),
    cfg.StrOpt('mount_options', default='defaults,noatime',
               help='Options to use when mounting a volume.'),
    cfg.IntOpt('max_instances_per_user', default=5,
               help='Default maximum number of instances per tenant.'),
    cfg.IntOpt('max_accepted_volume_size', default=5,
               help='Default maximum volume size (in GB) for an instance.'),
    cfg.IntOpt('max_volumes_per_user', default=20,
               help='Default maximum volume capacity (in GB) spanning across '
                    'all Trove volumes per tenant.'),
    cfg.IntOpt('max_backups_per_user', default=50,
               help='Default maximum number of backups created by a tenant.'),
    cfg.StrOpt('quota_driver', default='trove.quota.quota.DbQuotaDriver',
               help='Default driver to use for quota checks.'),
    cfg.StrOpt('taskmanager_queue', default='taskmanager',
               help='Message queue name the Taskmanager will listen to.'),
    cfg.StrOpt('conductor_queue', default='trove-conductor',
               help='Message queue name the Conductor will listen on.'),
    cfg.IntOpt('trove_conductor_workers',
               help='Number of workers for the Conductor service. The default '
               'will be the number of CPUs available.'),
    cfg.BoolOpt('use_nova_server_config_drive', default=False,
                help='Use config drive for file injection when booting '
                'instance.'),
    cfg.BoolOpt('use_nova_server_volume', default=False,
                help='Whether to provision a Cinder volume for the '
                     'Nova instance.'),
    cfg.BoolOpt('use_heat', default=False,
                help='Use Heat for provisioning.'),
    cfg.StrOpt('device_path', default='/dev/vdb',
               help='Device path for volume if volume support is enabled.'),
    cfg.StrOpt('default_datastore', default=None,
               help='The default datastore id or name to use if one is not '
               'provided by the user. If the default value is None, the field '
               'becomes required in the instance create request.'),
    cfg.StrOpt('datastore_manager', default=None,
               help='Manager class in the Guest Agent, set up by the '
               'Taskmanager on instance provision.'),
    cfg.StrOpt('block_device_mapping', default='vdb',
               help='Block device to map onto the created instance.'),
    cfg.IntOpt('server_delete_time_out', default=60,
               help='Maximum time (in seconds) to wait for a server delete.'),
    cfg.IntOpt('volume_time_out', default=60,
               help='Maximum time (in seconds) to wait for a volume attach.'),
    cfg.IntOpt('heat_time_out', default=60,
               help='Maximum time (in seconds) to wait for a Heat request to '
                    'complete.'),
    cfg.IntOpt('reboot_time_out', default=60 * 2,
               help='Maximum time (in seconds) to wait for a server reboot.'),
    cfg.IntOpt('dns_time_out', default=60 * 2,
               help='Maximum time (in seconds) to wait for a DNS entry add.'),
    cfg.IntOpt('resize_time_out', default=60 * 10,
               help='Maximum time (in seconds) to wait for a server resize.'),
    cfg.IntOpt('revert_time_out', default=60 * 10,
               help='Maximum time (in seconds) to wait for a server resize '
                    'revert.'),
    cfg.IntOpt('cluster_delete_time_out', default=60 * 3,
               help='Maximum time (in seconds) to wait for a cluster delete.'),
    cfg.ListOpt('root_grant', default=['ALL'],
                help="Permissions to grant to the 'root' user."),
    cfg.BoolOpt('root_grant_option', default=True,
                help="Assign the 'root' user GRANT permissions."),
    cfg.IntOpt('default_password_length', default=36,
               help='Character length of generated passwords.'),
    cfg.IntOpt('http_get_rate', default=200,
               help="Maximum number of HTTP 'GET' requests (per minute)."),
    cfg.IntOpt('http_post_rate', default=200,
               help="Maximum number of HTTP 'POST' requests (per minute)."),
    cfg.IntOpt('http_delete_rate', default=200,
               help="Maximum number of HTTP 'DELETE' requests (per minute)."),
    cfg.IntOpt('http_put_rate', default=200,
               help="Maximum number of HTTP 'PUT' requests (per minute)."),
    cfg.IntOpt('http_mgmt_post_rate', default=200,
               help="Maximum number of management HTTP 'POST' requests "
                    "(per minute)."),
    cfg.BoolOpt('hostname_require_valid_ip', default=True,
                help='Require user hostnames to be valid IP addresses.',
                deprecated_name='hostname_require_ipv4'),
    cfg.BoolOpt('trove_security_groups_support', default=True,
                help='Whether Trove should add Security Groups on create.'),
    cfg.StrOpt('trove_security_group_name_prefix', default='SecGroup',
               help='Prefix to use when creating Security Groups.'),
    cfg.StrOpt('trove_security_group_rule_cidr', default='0.0.0.0/0',
               help='CIDR to use when creating Security Group Rules.'),
    cfg.IntOpt('trove_api_workers',
               help='Number of workers for the API service. The default will '
               'be the number of CPUs available.'),
    cfg.IntOpt('usage_sleep_time', default=5,
               help='Time to sleep during the check for an active Guest.'),
    cfg.StrOpt('region', default='LOCAL_DEV',
               help='The region this service is located.'),
    cfg.StrOpt('backup_runner',
               default='trove.guestagent.backup.backup_types.InnoBackupEx',
               help='Runner to use for backups.'),
    cfg.DictOpt('backup_runner_options', default={},
                help='Additional options to be passed to the backup runner.'),
    cfg.BoolOpt('verify_swift_checksum_on_restore', default=True,
                help='Enable verification of Swift checksum before starting '
                'restore. Makes sure the checksum of original backup matches '
                'the checksum of the Swift backup file.'),
    cfg.StrOpt('storage_strategy', default='SwiftStorage',
               help="Default strategy to store backups."),
    cfg.StrOpt('storage_namespace',
               default='trove.guestagent.strategies.storage.swift',
               help='Namespace to load the default storage strategy from.'),
    cfg.StrOpt('backup_swift_container', default='database_backups',
               help='Swift container to put backups in.'),
    cfg.BoolOpt('backup_use_gzip_compression', default=True,
                help='Compress backups using gzip.'),
    cfg.BoolOpt('backup_use_openssl_encryption', default=True,
                help='Encrypt backups using OpenSSL.'),
    cfg.StrOpt('backup_aes_cbc_key', default='default_aes_cbc_key',
               help='Default OpenSSL aes_cbc key.'),
    cfg.BoolOpt('backup_use_snet', default=False,
                help='Send backup files over snet.'),
    cfg.IntOpt('backup_chunk_size', default=2 ** 16,
               help='Chunk size (in bytes) to stream to the Swift container. '
               'This should be in multiples of 128 bytes, since this is the '
               'size of an md5 digest block allowing the process to update '
               'the file checksum during streaming. '
               'See: http://stackoverflow.com/questions/1131220/'),
    cfg.IntOpt('backup_segment_max_size', default=2 * (1024 ** 3),
               help='Maximum size (in bytes) of each segment of the backup '
               'file.'),
    cfg.StrOpt('remote_dns_client',
               default='trove.common.remote.dns_client',
               help='Client to send DNS calls to.'),
    cfg.StrOpt('remote_guest_client',
               default='trove.common.remote.guest_client',
               help='Client to send Guest Agent calls to.'),
    cfg.StrOpt('remote_nova_client',
               default='trove.common.remote.nova_client',
               help='Client to send Nova calls to.'),
    cfg.StrOpt('remote_neutron_client',
               default='trove.common.remote.neutron_client',
               help='Client to send Neutron calls to.'),
    cfg.StrOpt('remote_cinder_client',
               default='trove.common.remote.cinder_client',
               help='Client to send Cinder calls to.'),
    cfg.StrOpt('remote_heat_client',
               default='trove.common.remote.heat_client',
               help='Client to send Heat calls to.'),
    cfg.StrOpt('remote_swift_client',
               default='trove.common.remote.swift_client',
               help='Client to send Swift calls to.'),
    cfg.StrOpt('exists_notification_transformer',
               help='Transformer for exists notifications.'),
    cfg.IntOpt('exists_notification_ticks', default=360,
               help='Number of report_intervals to wait between pushing '
                    'events (see report_interval).'),
    cfg.DictOpt('notification_service_id',
                default={'mysql': '2f3ff068-2bfb-4f70-9a9d-a6bb65bc084b',
                         'redis': 'b216ffc5-1947-456c-a4cf-70f94c05f7d0',
                         'cassandra': '459a230d-4e97-4344-9067-2a54a310b0ed',
                         'couchbase': 'fa62fe68-74d9-4779-a24e-36f19602c415',
                         'mongodb': 'c8c907af-7375-456f-b929-b637ff9209ee',
                         'postgresql': 'ac277e0d-4f21-40aa-b347-1ea31e571720'},
                help='Unique ID to tag notification events.'),
    cfg.StrOpt('nova_proxy_admin_user', default='',
               help="Admin username used to connect to Nova.", secret=True),
    cfg.StrOpt('nova_proxy_admin_pass', default='',
               help="Admin password used to connect to Nova.", secret=True),
    cfg.StrOpt('nova_proxy_admin_tenant_name', default='',
               help="Admin tenant used to connect to Nova.", secret=True),
    cfg.StrOpt('network_label_regex', default='^private$',
               help='Regular expression to match Trove network labels.'),
    cfg.StrOpt('ip_regex', default=None,
               help='List IP addresses that match this regular expression.'),
    cfg.StrOpt('black_list_regex', default=None,
               help='Exclude IP addresses that match this regular '
                    'expression.'),
    cfg.StrOpt('cloudinit_location', default='/etc/trove/cloudinit',
               help='Path to folder with cloudinit scripts.'),
    cfg.StrOpt('guest_config',
               default='$pybasedir/etc/trove/trove-guestagent.conf.sample',
               help='Path to the Guest Agent config file.'),
    cfg.DictOpt('datastore_registry_ext', default=dict(),
                help='Extension for default datastore managers. '
                     'Allows the use of custom managers for each of '
                     'the datastores supported by Trove.'),
    cfg.StrOpt('template_path', default='/etc/trove/templates/',
               help='Path which leads to datastore templates.'),
    cfg.BoolOpt('sql_query_logging', default=False,
                help='Allow insecure logging while '
                     'executing queries through SQLAlchemy.'),
    cfg.ListOpt('expected_filetype_suffixes', default=['json'],
                help='Filetype endings not to be reattached to an ID '
                     'by the utils method correct_id_with_req.'),
    cfg.ListOpt('default_neutron_networks', default=[],
                help='List of IDs for management networks which should be '
                     'attached to the instance regardless of what NICs '
                     'are specified in the create API call.'),
    cfg.IntOpt('max_header_line', default=16384,
               help='Maximum line size of message headers to be accepted. '
                    'max_header_line may need to be increased when using '
                    'large tokens (typically those generated by the '
                    'Keystone v3 API with big service catalogs).'),
    cfg.StrOpt('conductor_manager', default='trove.conductor.manager.Manager',
               help='Qualified class name to use for conductor manager.'),
    cfg.StrOpt('network_driver', default='trove.network.nova.NovaNetwork',
               help="Describes the actual network manager used for "
                    "the management of network attributes "
                    "(security groups, floating IPs, etc.)."),
    cfg.IntOpt('usage_timeout', default=600,
               help='Maximum time (in seconds) to wait for a Guest to become '
                    'active.'),
    cfg.IntOpt('restore_usage_timeout', default=36000,
               help='Maximum time (in seconds) to wait for a Guest instance '
                    'restored from a backup to become active.'),
    cfg.IntOpt('cluster_usage_timeout', default=675,
               help='Maximum time (in seconds) to wait for a cluster to '
                    'become active.'),
]

# Datastore specific option groups

# Mysql
mysql_group = cfg.OptGroup(
    'mysql', title='MySQL options',
    help="Oslo option group designed for MySQL datastore")
mysql_opts = [
    cfg.ListOpt('tcp_ports', default=["3306"],
                help='List of TCP ports and/or port ranges to open '
                     'in the security group (only applicable '
                     'if trove_security_groups_support is True).'),
    cfg.ListOpt('udp_ports', default=[],
                help='List of UDP ports and/or port ranges to open '
                     'in the security group (only applicable '
                     'if trove_security_groups_support is True).'),
    cfg.StrOpt('backup_strategy', default='InnoBackupEx',
               help='Default strategy to perform backups.',
               deprecated_name='backup_strategy',
               deprecated_group='DEFAULT'),
    cfg.StrOpt('replication_strategy', default='MysqlBinlogReplication',
               help='Default strategy for replication.'),
    cfg.StrOpt('replication_namespace',
               default='trove.guestagent.strategies.replication.mysql_binlog',
               help='Namespace to load replication strategies from.'),
    cfg.StrOpt('mount_point', default='/var/lib/mysql',
               help="Filesystem path for mounting "
                    "volumes if volume support is enabled."),
    cfg.BoolOpt('root_on_create', default=False,
                help='Enable the automatic creation of the root user for the '
                'service during instance-create. The generated password for '
                'the root user is immediately returned in the response of '
                "instance-create as the 'password' field."),
    cfg.IntOpt('usage_timeout', default=400,
               help='Maximum time (in seconds) to wait for a Guest to become '
                    'active.'),
    cfg.StrOpt('backup_namespace',
               default='trove.guestagent.strategies.backup.mysql_impl',
               help='Namespace to load backup strategies from.',
               deprecated_name='backup_namespace',
               deprecated_group='DEFAULT'),
    cfg.StrOpt('restore_namespace',
               default='trove.guestagent.strategies.restore.mysql_impl',
               help='Namespace to load restore strategies from.',
               deprecated_name='restore_namespace',
               deprecated_group='DEFAULT'),
    cfg.BoolOpt('volume_support', default=True,
                help='Whether to provision a Cinder volume for datadir.'),
    cfg.StrOpt('device_path', default='/dev/vdb',
               help='Device path for volume if volume support is enabled.'),
    cfg.DictOpt('backup_incremental_strategy',
                default={'InnoBackupEx': 'InnoBackupExIncremental'},
                help='Incremental Backup Runner based on the default '
                'strategy. For strategies that do not implement an '
                'incremental backup, the runner will use the default full '
                'backup.',
                deprecated_name='backup_incremental_strategy',
                deprecated_group='DEFAULT'),
]

# Percona
percona_group = cfg.OptGroup(
    'percona', title='Percona options',
    help="Oslo option group designed for Percona datastore")
percona_opts = [
    cfg.ListOpt('tcp_ports', default=["3306"],
                help='List of TCP ports and/or port ranges to open '
                     'in the security group (only applicable '
                     'if trove_security_groups_support is True).'),
    cfg.ListOpt('udp_ports', default=[],
                help='List of UDP ports and/or port ranges to open '
                     'in the security group (only applicable '
                     'if trove_security_groups_support is True).'),
    cfg.StrOpt('backup_strategy', default='InnoBackupEx',
               help='Default strategy to perform backups.',
               deprecated_name='backup_strategy',
               deprecated_group='DEFAULT'),
    cfg.StrOpt('replication_strategy', default='MysqlBinlogReplication',
               help='Default strategy for replication.'),
    cfg.StrOpt('replication_namespace',
               default='trove.guestagent.strategies.replication.mysql_binlog',
               help='Namespace to load replication strategies from.'),
    cfg.StrOpt('replication_user', default='slave_user',
               help='Userid for replication slave.'),
    cfg.StrOpt('replication_password', default='NETOU7897NNLOU',
               help='Password for replication slave user.'),
    cfg.StrOpt('mount_point', default='/var/lib/mysql',
               help="Filesystem path for mounting "
                    "volumes if volume support is enabled."),
    cfg.BoolOpt('root_on_create', default=False,
                help='Enable the automatic creation of the root user for the '
                'service during instance-create. The generated password for '
                'the root user is immediately returned in the response of '
                "instance-create as the 'password' field."),
    cfg.IntOpt('usage_timeout', default=450,
               help='Maximum time (in seconds) to wait for a Guest to become '
                    'active.'),
    cfg.StrOpt('backup_namespace',
               default='trove.guestagent.strategies.backup.mysql_impl',
               help='Namespace to load backup strategies from.',
               deprecated_name='backup_namespace',
               deprecated_group='DEFAULT'),
    cfg.StrOpt('restore_namespace',
               default='trove.guestagent.strategies.restore.mysql_impl',
               help='Namespace to load restore strategies from.',
               deprecated_name='restore_namespace',
               deprecated_group='DEFAULT'),
    cfg.BoolOpt('volume_support', default=True,
                help='Whether to provision a Cinder volume for datadir.'),
    cfg.StrOpt('device_path', default='/dev/vdb',
               help='Device path for volume if volume support is enabled.'),
    cfg.DictOpt('backup_incremental_strategy',
                default={'InnoBackupEx': 'InnoBackupExIncremental'},
                help='Incremental Backup Runner based on the default '
                'strategy. For strategies that do not implement an '
                'incremental backup, the runner will use the default full '
                'backup.',
                deprecated_name='backup_incremental_strategy',
                deprecated_group='DEFAULT'),
]

# Redis
redis_group = cfg.OptGroup(
    'redis', title='Redis options',
    help="Oslo option group designed for Redis datastore")
redis_opts = [
    cfg.ListOpt('tcp_ports', default=["6379"],
                help='List of TCP ports and/or port ranges to open '
                     'in the security group (only applicable '
                     'if trove_security_groups_support is True).'),
    cfg.ListOpt('udp_ports', default=[],
                help='List of UDP ports and/or port ranges to open '
                     'in the security group (only applicable '
                     'if trove_security_groups_support is True).'),
    cfg.StrOpt('backup_strategy', default=None,
               help='Default strategy to perform backups.',
               deprecated_name='backup_strategy',
               deprecated_group='DEFAULT'),
    cfg.DictOpt('backup_incremental_strategy', default={},
                help='Incremental Backup Runner based on the default '
                'strategy. For strategies that do not implement an '
                'incremental, the runner will use the default full backup.',
                deprecated_name='backup_incremental_strategy',
                deprecated_group='DEFAULT'),
    cfg.StrOpt('replication_strategy', default=None,
               help='Default strategy for replication.'),
    cfg.StrOpt('mount_point', default='/var/lib/redis',
               help="Filesystem path for mounting "
               "volumes if volume support is enabled."),
    cfg.BoolOpt('volume_support', default=False,
                help='Whether to provision a Cinder volume for datadir.'),
    cfg.StrOpt('device_path', default=None,
               help='Device path for volume if volume support is enabled.'),
    cfg.StrOpt('backup_namespace', default=None,
               help='Namespace to load backup strategies from.',
               deprecated_name='backup_namespace',
               deprecated_group='DEFAULT'),
    cfg.StrOpt('restore_namespace', default=None,
               help='Namespace to load restore strategies from.',
               deprecated_name='restore_namespace',
               deprecated_group='DEFAULT'),
]

# Cassandra
cassandra_group = cfg.OptGroup(
    'cassandra', title='Cassandra options',
    help="Oslo option group designed for Cassandra datastore")
cassandra_opts = [
    cfg.ListOpt('tcp_ports', default=["7000", "7001", "9042", "9160"],
                help='List of TCP ports and/or port ranges to open '
                     'in the security group (only applicable '
                     'if trove_security_groups_support is True).'),
    cfg.ListOpt('udp_ports', default=[],
                help='List of UDP ports and/or port ranges to open '
                     'in the security group (only applicable '
                     'if trove_security_groups_support is True).'),
    cfg.StrOpt('backup_strategy', default=None,
               help='Default strategy to perform backups.',
               deprecated_name='backup_strategy',
               deprecated_group='DEFAULT'),
    cfg.DictOpt('backup_incremental_strategy', default={},
                help='Incremental Backup Runner based on the default '
                'strategy. For strategies that do not implement an '
                'incremental, the runner will use the default full backup.',
                deprecated_name='backup_incremental_strategy',
                deprecated_group='DEFAULT'),
    cfg.StrOpt('replication_strategy', default=None,
               help='Default strategy for replication.'),
    cfg.StrOpt('mount_point', default='/var/lib/cassandra',
               help="Filesystem path for mounting "
               "volumes if volume support is enabled."),
    cfg.BoolOpt('volume_support', default=True,
                help='Whether to provision a Cinder volume for datadir.'),
    cfg.StrOpt('device_path', default='/dev/vdb',
               help='Device path for volume if volume support is enabled.'),
    cfg.StrOpt('backup_namespace', default=None,
               help='Namespace to load backup strategies from.',
               deprecated_name='backup_namespace',
               deprecated_group='DEFAULT'),
    cfg.StrOpt('restore_namespace', default=None,
               help='Namespace to load restore strategies from.',
               deprecated_name='restore_namespace',
               deprecated_group='DEFAULT'),
]

# Couchbase
couchbase_group = cfg.OptGroup(
    'couchbase', title='Couchbase options',
    help="Oslo option group designed for Couchbase datastore")
couchbase_opts = [
    cfg.ListOpt('tcp_ports',
                default=["8091", "8092", "4369", "11209-11211",
                         "21100-21199"],
                help='List of TCP ports and/or port ranges to open '
                     'in the security group (only applicable '
                     'if trove_security_groups_support is True).'),
    cfg.ListOpt('udp_ports', default=[],
                help='List of UDP ports and/or port ranges to open '
                     'in the security group (only applicable '
                     'if trove_security_groups_support is True).'),
    cfg.StrOpt('backup_strategy', default='CbBackup',
               help='Default strategy to perform backups.',
               deprecated_name='backup_strategy',
               deprecated_group='DEFAULT'),
    cfg.DictOpt('backup_incremental_strategy', default={},
                help='Incremental Backup Runner based on the default '
                'strategy. For strategies that do not implement an '
                'incremental, the runner will use the default full backup.',
                deprecated_name='backup_incremental_strategy',
                deprecated_group='DEFAULT'),
    cfg.StrOpt('replication_strategy', default=None,
               help='Default strategy for replication.'),
    cfg.StrOpt('mount_point', default='/var/lib/couchbase',
               help="Filesystem path for mounting "
               "volumes if volume support is enabled."),
    cfg.BoolOpt('root_on_create', default=True,
                help='Enable the automatic creation of the root user for the '
                'service during instance-create. The generated password for '
                'the root user is immediately returned in the response of '
                "instance-create as the 'password' field."),
    cfg.StrOpt('backup_namespace',
               default='trove.guestagent.strategies.backup.couchbase_impl',
               help='Namespace to load backup strategies from.',
               deprecated_name='backup_namespace',
               deprecated_group='DEFAULT'),
    cfg.StrOpt('restore_namespace',
               default='trove.guestagent.strategies.restore.couchbase_impl',
               help='Namespace to load restore strategies from.',
               deprecated_name='restore_namespace',
               deprecated_group='DEFAULT'),
    cfg.BoolOpt('volume_support', default=True,
                help='Whether to provision a Cinder volume for datadir.'),
    cfg.StrOpt('device_path', default='/dev/vdb',
               help='Device path for volume if volume support is enabled.'),
]

# MongoDB
mongodb_group = cfg.OptGroup(
    'mongodb', title='MongoDB options',
    help="Oslo option group designed for MongoDB datastore")
mongodb_opts = [
    cfg.ListOpt('tcp_ports', default=["2500", "27017"],
                help='List of TCP ports and/or port ranges to open '
                     'in the security group (only applicable '
                     'if trove_security_groups_support is True).'),
    cfg.ListOpt('udp_ports', default=[],
                help='List of UPD ports and/or port ranges to open '
                     'in the security group (only applicable '
                     'if trove_security_groups_support is True).'),
    cfg.StrOpt('backup_strategy', default=None,
               help='Default strategy to perform backups.',
               deprecated_name='backup_strategy',
               deprecated_group='DEFAULT'),
    cfg.DictOpt('backup_incremental_strategy', default={},
                help='Incremental Backup Runner based on the default '
                'strategy. For strategies that do not implement an '
                'incremental, the runner will use the default full backup.',
                deprecated_name='backup_incremental_strategy',
                deprecated_group='DEFAULT'),
    cfg.StrOpt('replication_strategy', default=None,
               help='Default strategy for replication.'),
    cfg.StrOpt('mount_point', default='/var/lib/mongodb',
               help="Filesystem path for mounting "
               "volumes if volume support is enabled."),
    cfg.BoolOpt('volume_support', default=True,
                help='Whether to provision a Cinder volume for datadir.'),
    cfg.StrOpt('device_path', default='/dev/vdb',
               help='Device path for volume if volume support is enabled.'),
    cfg.IntOpt('num_config_servers_per_cluster', default=3,
               help='The number of config servers to create per cluster.'),
    cfg.IntOpt('num_query_routers_per_cluster', default=1,
               help='The number of query routers (mongos) to create '
                    'per cluster.'),
    cfg.BoolOpt('cluster_support', default=True,
                help='Enable clusters to be created and managed.'),
    cfg.StrOpt('api_strategy',
               default='trove.common.strategies.cluster.mongodb.api.'
                       'MongoDbAPIStrategy',
               help='Class that implements datastore-specific API logic.'),
    cfg.StrOpt('taskmanager_strategy',
               default='trove.common.strategies.cluster.mongodb.taskmanager.'
                       'MongoDbTaskManagerStrategy',
               help='Class that implements datastore-specific task manager '
                    'logic.'),
    cfg.StrOpt('guestagent_strategy',
               default='trove.common.strategies.cluster.mongodb.guestagent.'
                       'MongoDbGuestAgentStrategy',
               help='Class that implements datastore-specific Guest Agent API '
                    'logic.'),
    cfg.StrOpt('backup_namespace', default=None,
               help='Namespace to load backup strategies from.',
               deprecated_name='backup_namespace',
               deprecated_group='DEFAULT'),
    cfg.StrOpt('restore_namespace', default=None,
               help='Namespace to load restore strategies from.',
               deprecated_name='restore_namespace',
               deprecated_group='DEFAULT'),
]

# PostgreSQL
postgresql_group = cfg.OptGroup(
    'postgresql', title='PostgreSQL options',
    help="Oslo option group for the PostgreSQL datastore.")
postgresql_opts = [
    cfg.ListOpt('tcp_ports', default=["5432"],
                help='List of TCP ports and/or port ranges to open '
                     'in the security group (only applicable '
                     'if trove_security_groups_support is True).'),
    cfg.ListOpt('udp_ports', default=[],
                help='List of UPD ports and/or port ranges to open '
                     'in the security group (only applicable '
                     'if trove_security_groups_support is True).'),
    cfg.StrOpt('backup_strategy', default='PgDump',
               help='Default strategy to perform backups.'),
    cfg.DictOpt('backup_incremental_strategy', default={},
                help='Incremental Backup Runner based on the default '
                'strategy. For strategies that do not implement an '
                'incremental, the runner will use the default full backup.'),
    cfg.StrOpt('mount_point', default='/var/lib/postgresql',
               help="Filesystem path for mounting "
               "volumes if volume support is enabled."),
    cfg.BoolOpt('root_on_create', default=False,
                help='Enable the automatic creation of the root user for the '
                'service during instance-create. The generated password for '
                'the root user is immediately returned in the response of '
                "instance-create as the 'password' field."),
    cfg.StrOpt('backup_namespace',
               default='trove.guestagent.strategies.backup.postgresql_impl',
               help='Namespace to load backup strategies from.'),
    cfg.StrOpt('restore_namespace',
               default='trove.guestagent.strategies.restore.postgresql_impl',
               help='Namespace to load restore strategies from.'),
    cfg.BoolOpt('volume_support', default=True,
                help='Whether to provision a Cinder volume for datadir.'),
    cfg.StrOpt('device_path', default='/dev/vdb'),
    cfg.ListOpt('ignore_users', default=['os_admin', 'postgres', 'root']),
    cfg.ListOpt('ignore_dbs', default=['postgres']),
]

# RPC version groups
upgrade_levels = cfg.OptGroup(
    'upgrade_levels',
    title='RPC upgrade levels group for handling versions',
    help='Contains the support version caps for each RPC API')

rpcapi_cap_opts = [
    cfg.StrOpt(
        'taskmanager', default="icehouse",
        help='Set a version cap for messages sent to taskmanager services'),
    cfg.StrOpt(
        'guestagent', default="icehouse",
        help='Set a version cap for messages sent to guestagent services'),
    cfg.StrOpt(
        'conductor', default="icehouse",
        help='Set a version cap for messages sent to conductor services'),
]

CONF = cfg.CONF

CONF.register_opts(path_opts)
CONF.register_opts(common_opts)

CONF.register_group(mysql_group)
CONF.register_group(percona_group)
CONF.register_group(redis_group)
CONF.register_group(cassandra_group)
CONF.register_group(couchbase_group)
CONF.register_group(mongodb_group)
CONF.register_group(postgresql_group)

CONF.register_opts(mysql_opts, mysql_group)
CONF.register_opts(percona_opts, percona_group)
CONF.register_opts(redis_opts, redis_group)
CONF.register_opts(cassandra_opts, cassandra_group)
CONF.register_opts(couchbase_opts, couchbase_group)
CONF.register_opts(mongodb_opts, mongodb_group)
CONF.register_opts(postgresql_opts, postgresql_group)

CONF.register_opts(rpcapi_cap_opts, upgrade_levels)


def custom_parser(parsername, parser):
    CONF.register_cli_opt(cfg.SubCommandOpt(parsername, handler=parser))


def parse_args(argv, default_config_files=None):
    cfg.CONF(args=argv[1:],
             project='trove',
             version=trove.__version__,
             default_config_files=default_config_files)
