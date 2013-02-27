# -*- encoding: utf-8 -*-
#
# Copyright © 2013 eNovance <licensing@enovance.com>
#
# Author: Mehdi Abaakouk <mehdi.abaakouk@enovance.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""Test for ceilometer/alarm/storage/impl_sqlalchemy.py
"""

import logging
import os
import sqlalchemy

from oslo.config import cfg

from tests.alarm.storage import base
from ceilometer.alarm.storage import impl_sqlalchemy

LOG = logging.getLogger(__name__)

CEILOMETER_TEST_LIVE = bool(int(os.environ.get('CEILOMETER_TEST_LIVE', 0)))
if CEILOMETER_TEST_LIVE:
    MYSQL_DBNAME = 'ceilometer_test'
    MYSQL_BASE_URL = 'mysql://ceilometer:somepass@localhost/'
    MYSQL_URL = MYSQL_BASE_URL + MYSQL_DBNAME


class Connection(impl_sqlalchemy.Connection):

    def _get_connection(self, conf):
        try:
            return super(Connection, self)._get_connection(conf)
        except:
            LOG.debug('Unable to connect to %s' %
                      conf.alarm_database_connection)
            raise


class SQLAlchemyEngine(base.DBEngineBase):

    def clean_up(self):
        engine_conn = self.session.bind.connect()
        if CEILOMETER_TEST_LIVE:
            engine_conn.execute('drop database %s' % MYSQL_DBNAME)
            engine_conn.execute('create database %s' % MYSQL_DBNAME)
        # needed for sqlite in-memory db to destroy
        self.session.close_all()
        self.session.bind.dispose()

    def get_connection(self):
        self.conf = cfg.CONF
        self.conf.alarm_database_connection = 'sqlite://'
        # Use a real MySQL server if we can connect, but fall back
        # to a Sqlite in-memory connection if we cannot.
        if CEILOMETER_TEST_LIVE:
            # should pull from conf file but for now manually specified
            # just make sure ceilometer_test db exists in mysql
            self.conf.alarm_database_connection = MYSQL_URL
            engine = sqlalchemy.create_engine(MYSQL_BASE_URL)
            engine_conn = engine.connect()
            try:
                engine_conn.execute('drop database %s' % MYSQL_DBNAME)
            except sqlalchemy.exc.OperationalError:
                pass
            engine_conn.execute('create database %s' % MYSQL_DBNAME)

        self.conn = Connection(self.conf)
        self.session = self.conn.session
        self.conn.upgrade()
        return self.conn


class SQLAlchemyEngineTestBase(base.DBTestBase):

    def get_engine(cls):
        return SQLAlchemyEngine()


class AlarmTest(base.AlarmTest, SQLAlchemyEngineTestBase):
    pass
