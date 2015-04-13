# Copyright 2015 IBM Corp.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

TIMEOUT = 1200
DB2_INSTANCE_OWNER = "db2inst1"
ENABLE_AUTOSTART = (
    "/opt/ibm/db2/V10.5/instance/db2iauto -on " + DB2_INSTANCE_OWNER)
DISABLE_AUTOSTART = (
    "/opt/ibm/db2/V10.5/instance/db2iauto -off " + DB2_INSTANCE_OWNER)
START_DB2 = "db2start"
STOP_DB2 = "db2 force application all; db2 terminate; db2stop"
DB2_STATUS = ("ps -ef | grep " + DB2_INSTANCE_OWNER + " | grep db2sysc |"
              "grep -v grep | wc -l")
CHANGE_DB_DIR_OWNER = "sudo chown " + DB2_INSTANCE_OWNER + " %(datadir)s"
CHANGE_DB_DIR_GROUP_OWNER = (
    "sudo chgrp " + DB2_INSTANCE_OWNER + " %(datadir)s")
CREATE_DB_COMMAND = "db2 create database %(dbname)s"
DELETE_DB_COMMAND = "db2 drop database %(dbname)s"
LIST_DB_COMMAND = (
    "db2 list database directory | grep -B6 -i indirect | "
    "grep 'Database name' | sed 's/.*= //'")
CREATE_USER_COMMAND = (
    'sudo useradd -m -d /home/%(login)s %(login)s;'
    'sudo echo %(login)s:%(passwd)s |sudo  chpasswd')
GRANT_USER_ACCESS = (
    "db2 connect to %(dbname)s; "
    "db2 GRANT DBADM,CREATETAB,BINDADD,CONNECT,DATAACCESS "
    "ON DATABASE TO USER %(login)s; db2 connect reset")
DELETE_USER_COMMAND = 'sudo userdel -r %(login)s'
REVOKE_USER_ACCESS = (
    "db2 connect to %(dbname)s; "
    "db2 REVOKE DBADM,CREATETAB,BINDADD,CONNECT,DATAACCESS "
    "ON DATABASE FROM USER %(login)s; db2 connect reset")
LIST_DB_USERS = (
    "db2 +o  connect to %(dbname)s; "
    "db2 -x  select grantee, dataaccessauth from sysibm.sysdbauth; "
    "db2 connect reset")
