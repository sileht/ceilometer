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
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""Tests for ceilometer/alarm/service.py
"""

import os
import tempfile
from datetime import datetime

from mock import patch
from mock import MagicMock
from mox import IgnoreArg

from oslo.config import cfg

from ceilometer import storage
from ceilometer.alarm.service import AlarmService
from ceilometer.alarm.alarm import Alarm
from ceilometer.collector import meter as collector_meter
from ceilometer.openstack.common import jsonutils
from ceilometer.tests import base as tests_base


TEST_ALARM = {
    'name': 'SwiftObjectAlarm',
    'counter_name': 'storage.objects',
    'comparison_operator': 'ge',
    'threshold': 2.0,
    'statistic': 'avg',
    'period': 60,
    'ok_action': 'touch ceilometer_alarmservice_test_ok',
}

TEST_INVALID_ALARM = {
    'name': 'SwiftObjectAlarm',
    'counter_name': 'storage.objects',
    'comparison_operator': 'invalid',
    'threshold': 2.0,
    'statistic': 'avg',
    'period': 60,
}

TEST_ALARMS_JSON = jsonutils.dumps([TEST_ALARM])
TEST_INVALID_ALARMS_JSON = jsonutils.dumps([TEST_INVALID_ALARM])


class TestAlarmService(tests_base.TestCase):
    def _remove_alarm_testfile(self):
        for f in ['ceilometer_alarmservice_test_ok',
                  cfg.CONF.alarms_file]:
            if os.path.exists(f):
                os.unlink(f)

    def setUp(self):
        super(TestAlarmService, self).setUp()
        self.srv = AlarmService('the-host', 'the-topic')
        self.ctx = None

    def tearDown(self):
        super(TestAlarmService, self).tearDown()
        self._remove_alarm_testfile()

    @patch('ceilometer.pipeline.setup_pipeline', MagicMock())
    def test_init_host(self):
        cfg.CONF.database_connection = 'log://localhost'
        cfg.CONF.alarms_file = tempfile.mktemp()
        with open(cfg.CONF.alarms_file, 'w') as f:
            f.write(TEST_ALARMS_JSON)

        # If we try to create a real RPC connection, init_host() never
        # returns. Mock it out so we can establish the manager
        # configuration.
        with patch('ceilometer.openstack.common.rpc.create_connection'):
            self.srv.start()

    def test_load_alarms(self):
        cfg.CONF([])
        cfg.CONF.alarms_file = tempfile.mktemp()
        with open(cfg.CONF.alarms_file, 'w') as f:
            f.write(TEST_ALARMS_JSON)
        self.srv._load_alarms()
        self.assertEqual(self.srv._alarms_cache['data'], TEST_ALARMS_JSON)

    def test_load_invalid_alarms(self):
        cfg.CONF([])
        cfg.CONF.alarms_file = tempfile.mktemp()
        with open(cfg.CONF.alarms_file, 'w') as f:
            f.write(TEST_INVALID_ALARMS_JSON)
        self.srv._load_alarms()
        self.assertEqual(len(self.srv._alarms), 0)

    def test_init_file_not_found(self):
        cfg.CONF([])
        cfg.CONF.alarms_file = 'foobar.json.does.not.exist'
        self.assertRaises(cfg.ConfigFilesNotFoundError, self.srv._load_alarms)

    def test_timestamp_tzinfo_conversion(self):
        msg = {'counter_name': 'test',
               'resource_id': self.id(),
               'counter_volume': 1,
               'timestamp': '2012-09-30T15:31:50.262-08:00',
               }
        msg['message_signature'] = collector_meter.compute_signature(
            msg,
            cfg.CONF.metering_secret,
        )

        expected = {}
        expected.update(msg)
        expected['timestamp'] = datetime(2012, 9, 30, 23, 31, 50, 262000)

        self.mox.StubOutWithMock(self.srv, '_check_alarms')
        self.srv._check_alarms(expected)
        self.mox.ReplayAll()

        self.srv.record_metering_data(self.ctx, msg)
        self.mox.VerifyAll()

    def test_check_alarms(self):
        meter = {'counter_name': 'storage.objects'}
        alarm = Alarm(**TEST_ALARM)
        self.srv._alarms = [alarm]

        self.srv.storage_conn = self.mox.CreateMock(storage.base.Connection)
        self.srv.storage_conn.get_meter_statistics(
            IgnoreArg(),
            period=alarm.period
        ).AndReturn([{'avg': 0.0, 'period': alarm.period,
                      'duration': float(alarm.period) / 60.0}])

        self.mox.ReplayAll()

        self.srv._check_alarms(meter)

        self.mox.VerifyAll()
        self.assertTrue(os.path.exists('ceilometer_alarmservice_test_ok'))
