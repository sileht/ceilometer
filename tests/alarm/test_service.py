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

import eventlet
import requests

from mock import patch
from mock import MagicMock
import mox

from oslo.config import cfg

from ceilometer.alarm.storage import base
from ceilometer.alarm.service import AlarmService
from ceilometer.alarm.alarm import Alarm, ALARM_OK
from ceilometer.alarm.aggregated_metric import AggregatedMetric
from ceilometer.collector import meter as collector_meter
from ceilometer.openstack.common import timeutils
from ceilometer.tests import base as tests_base

cfg.CONF.import_opt("alarm_database_connection", "ceilometer.alarm.storage")

TEST_ALARM = {
    'id': 1,
    'name': 'SwiftObjectAlarm',
    'counter_name': 'storage.objects',
    'comparison_operator': 'ge',
    'project_id': '',
    'user_id': '',
    'threshold': 2.0,
    'statistic': 'average',
    'evaluation_period': 2,
    'aggregate_period': 60,
    'ok_actions': ['http://localhost:8080/test_ok?state=%(state)s'],
    'alarm_actions': ['http://localhost:8080/test_alarm?state=%(state)s'],
    'insufficient_data_actions':
    ['http://localhost:8080/test_insufficient_data?state=%(state)s']
}


class TestAlarmService(tests_base.TestCase):
    def _remove_alarm_testfile(self):
        for f in ['ceilometer_alarmservice_test_ok']:
            if os.path.exists(f):
                os.unlink(f)

    def setUp(self):
        super(TestAlarmService, self).setUp()
        self.srv = AlarmService('the-host', 'the-topic')
        self.ctx = None

    def tearDown(self):
        super(TestAlarmService, self).tearDown()
        self._remove_alarm_testfile()

    def _fake_refresh_alarm_cache(self):
        pass

    @patch('ceilometer.pipeline.setup_pipeline', MagicMock())
    def test_init_host(self):
        cfg.CONF.alarm_database_connection = 'sqlite:///'

        self.srv._refresh_alarm_cache = self._fake_refresh_alarm_cache
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

    def test_check_alarms_that_update_a_aggregated_metric(self):
        now = timeutils.utcnow()

        value = 0.0
        meter = {'counter_name': 'storage.objects', 'counter_volume': value,
                 'counter_unit': 'n'}
        alarm = Alarm(**TEST_ALARM)

        self.mox.StubOutWithMock(eventlet, 'spawn_n')

        eventlet.spawn_n(requests.post,
                         'http://localhost:8080/test_ok?state=1',
                         data=mox.ContainsKeyValue("name", TEST_ALARM["name"]))

        # Mock all db calls
        self.srv.storage_conn = self.mox.CreateMock(base.Connection)
        self.srv.storage_conn.alarm_list(enabled=True).AndReturn(
            (alarm.id, ))
        self.srv.storage_conn.alarm_get(alarm.id).AndReturn(alarm)

        self.srv.storage_conn.aggregated_metric_list(alarm.id).AndReturn(
            (4, 3, 2, 1))

        aggregated_metrics = [
            {'id': 4, 'sample_count': 1, 'timestamp': now - datetime.timedelta(
                seconds=(alarm.aggregate_period)), 'average': 1.0},
            {'id': 3, 'sample_count': 1, 'timestamp': now - datetime.timedelta(
                seconds=(alarm.aggregate_period * 2)), 'average': 1.0},
            {'id': 2, 'sample_count': 1, 'timestamp': now - datetime.timedelta(
                seconds=(alarm.aggregate_period * 3)), 'average': 1.0},
            {'id': 1, 'sample_count': 1, 'timestamp': now - datetime.timedelta(
                seconds=(alarm.aggregate_period * 4)), 'average': 1.0}
        ]
        for a in aggregated_metrics:
            self.srv.storage_conn.aggregated_metric_get(a['id']).AndReturn(
                AggregatedMetric(alarm.id, **a))

        self.srv.storage_conn.aggregated_metric_update(
            mox.IsA(AggregatedMetric))
        self.srv.storage_conn.aggregated_metric_delete(1)

        self.srv.storage_conn.alarm_update(alarm)

        self.mox.ReplayAll()
        self.srv._refresh_alarm_cache()
        self.srv._check_alarms(meter)
        self.assertEquals(alarm.state, ALARM_OK)
        self.mox.VerifyAll()

    def test_check_alarms_that_add_a_aggregated_metric(self):
        now = timeutils.utcnow()

        value = 0.0
        meter = {'counter_name': 'storage.objects', 'counter_volume': value,
                 'counter_unit': 'n'}
        alarm = Alarm(**TEST_ALARM)

        self.mox.StubOutWithMock(eventlet, 'spawn_n')

        eventlet.spawn_n(requests.post,
                         'http://localhost:8080/test_ok?state=1',
                         data=mox.ContainsKeyValue("name", TEST_ALARM["name"]))

        # Mock all db calls
        self.srv.storage_conn = self.mox.CreateMock(base.Connection)
        self.srv.storage_conn.alarm_list(enabled=True).AndReturn(
            (alarm.id, ))
        self.srv.storage_conn.alarm_get(alarm.id).AndReturn(alarm)

        self.srv.storage_conn.aggregated_metric_list(alarm.id).AndReturn(
            (4, 3, 2, 1))

        aggregated_metrics = [
            {'id': 4, 'sample_count': 1, 'timestamp': now - datetime.timedelta(
                seconds=(alarm.aggregate_period * 2)), 'average': 1.0},
            {'id': 3, 'sample_count': 1, 'timestamp': now - datetime.timedelta(
                seconds=(alarm.aggregate_period * 3)), 'average': 1.0},
            {'id': 2, 'sample_count': 1, 'timestamp': now - datetime.timedelta(
                seconds=(alarm.aggregate_period * 4)), 'average': 1.0},
            {'id': 1, 'sample_count': 1, 'timestamp': now - datetime.timedelta(
                seconds=(alarm.aggregate_period * 5)), 'average': 1.0}
        ]
        for a in aggregated_metrics:
            self.srv.storage_conn.aggregated_metric_get(a['id']).AndReturn(
                AggregatedMetric(alarm.id, **a))

        self.srv.storage_conn.aggregated_metric_add(
            mox.IsA(AggregatedMetric))
        self.srv.storage_conn.aggregated_metric_delete(2)
        self.srv.storage_conn.aggregated_metric_delete(1)

        self.srv.storage_conn.alarm_update(alarm)

        self.mox.ReplayAll()
        self.srv._load_alarm_cache()
        self.srv._check_alarms(meter)
        self.assertEquals(alarm.state, ALARM_OK)
        self.mox.VerifyAll()
