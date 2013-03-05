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
import datetime

from mock import patch
from mock import MagicMock
from mox import IsA

from oslo.config import cfg

from ceilometer.alarm import storage  # to load cfg options
from ceilometer.alarm.storage import base
from ceilometer.alarm.service import AlarmService
from ceilometer.alarm.alarm import Alarm, ALARM_OK
from ceilometer.collector import meter as collector_meter
from ceilometer.openstack.common import timeutils
from ceilometer.tests import base as tests_base


TEST_ALARM = {
    'id': '1',
    'name': 'SwiftObjectAlarm',
    'counter_name': 'storage.objects',
    'comparison_operator': 'ge',
    'threshold': 2.0,
    'statistic': 'average',
    'aggregate_period': 60,
    'evaluation_period': 1,
    'ok_actions': ['touch ceilometer_alarmservice_test_ok'],
}


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
        cfg.CONF.database_alarm_connection = 'sqlite:///'

        # If we try to create a real RPC connection, init_host() never
        # returns. Mock it out so we can establish the manager
        # configuration.
        with patch('ceilometer.openstack.common.rpc.create_connection'):
            self.srv.start()

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
        expected['timestamp'] = \
            datetime.datetime(2012, 9, 30, 23, 31, 50, 262000)

        self.mox.StubOutWithMock(self.srv, '_check_alarms')
        self.srv._check_alarms(expected)
        self.mox.ReplayAll()

        self.srv.record_metering_data(self.ctx, msg)
        self.mox.VerifyAll()

    def test_check_alarms(self):
        now = timeutils.utcnow()

        value = 0.0
        meter = {'counter_name': 'storage.objects', 'counter_volume': value}
        alarm = Alarm(**TEST_ALARM)

        self.srv._alarms = [alarm]

        self.srv.storage_conn = self.mox.CreateMock(base.Connection)
        self.srv.storage_conn.alarm_list(
            counter_name=meter['counter_name']
        ).AndReturn([TEST_ALARM])

        self.srv.storage_conn.aggregated_metric_list(
            alarm.id,
            limit=alarm.evaluation_period,
            start=IsA(datetime.datetime)
        ).AndReturn([
            {'id': 1, 'timestamp': now - datetime.timedelta(
                seconds=((alarm.evaluation_period / 30))), 'average': 1.0},
            {'id': 2, 'timestamp': now - datetime.timedelta(
                seconds=((alarm.evaluation_period / 30) * 2)), 'average': 1.0},
        ])

        self.srv.storage_conn.aggregated_metric_update(
            1, {'id': 1, 'sample_count': 1.0, 'average': value,
                'maximum': value, 'minimum': value, 'sum': value,
                'timestamp': IsA(datetime.datetime)}
        )
        self.srv.storage_conn.alarm_update_state(
            alarm.id, ALARM_OK, IsA(datetime.datetime)
        )

        self.mox.ReplayAll()

        self.srv._check_alarms(meter)

        self.mox.VerifyAll()
        self.assertTrue(os.path.exists('ceilometer_alarmservice_test_ok'))
