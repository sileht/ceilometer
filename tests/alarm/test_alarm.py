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
"""Tests for ceilometer/alarm/alarm.py
"""

import os

from mox import IgnoreArg

from ceilometer import storage
from ceilometer.alarm.alarm import Alarm, ALARM_OK, ALARM_ALARM, \
    ALARM_INSUFFICIENT_DATA
from ceilometer.exception import InvalidComparisonOperator
from ceilometer.tests import base as tests_base

TEST_ALARM = {
    'name': 'SwiftObjectAlarm',
    'counter_name': 'storage.objects',
    'comparison_operator': 'ge',
    'threshold': 2.0,
    'statistic': 'avg',
    'period': 60,
    'ok_action': 'touch ceilometer_alarm_test_ok',
    'alarm_action': 'touch ceilometer_alarm_test_alarm',
    'insufficient_data_action': 'touch ceilometer_alarm_test_insufficient_data'
}


class TestAlarm(tests_base.TestCase):
    def _remove_alarm_testfile(self):
        for f in ['ceilometer_alarm_test_alarm',
                  'ceilometer_alarm_test_ok',
                  'ceilometer_alarm_test_insufficient_data']:
            if os.path.exists(f):
                os.unlink(f)

    def tearDown(self):
        super(TestAlarm, self).tearDown()
        self._remove_alarm_testfile()

    def test_create_alarm(self):
        alarm = Alarm('name', 'counter_name', 'eq', 2.0, 'sum', 60,
                      resource_id='id', ok_action='ok_action',
                      alarm_action='alarm_action',
                      insufficient_data_action='insufficient_data_action')
        self.assertEqual(alarm.name, 'name')
        self.assertEqual(alarm.counter_name, 'counter_name')
        self.assertEqual(alarm.comparison_operator, 'eq')
        self.assertEqual(alarm.threshold, 2.0)
        self.assertEqual(alarm.statistic, 'sum')
        self.assertEqual(alarm.period, 60)
        self.assertEqual(alarm.resource_id, 'id')
        self.assertEqual(alarm.ok_action, 'ok_action')
        self.assertEqual(alarm.alarm_action, 'alarm_action')
        self.assertTrue(alarm.insufficient_data_action ==
                        'insufficient_data_action')

    def test_create_alarm_with_default(self):
        alarm = Alarm('name', 'counter_name', 'eq', 2.0, 'sum', 60)
        self.assertEqual(alarm.name, 'name')
        self.assertEqual(alarm.counter_name, 'counter_name')
        self.assertEqual(alarm.comparison_operator, 'eq')
        self.assertEqual(alarm.threshold, 2.0)
        self.assertEqual(alarm.statistic, 'sum')
        self.assertEqual(alarm.period, 60)
        self.assertTrue(alarm.resource_id is None)
        self.assertTrue(alarm.ok_action is None)
        self.assertTrue(alarm.alarm_action is None)
        self.assertTrue(alarm.insufficient_data_action is None)

    def test_create_invalid_alarm(self):
        self.assertRaises(InvalidComparisonOperator, Alarm, 'name',
                          'counter_name', 'invalid_operator', 2.0, 'avg', 60)

    def test_not_match_meter(self):
        meter = {'counter_name': 'other_metric'}
        alarm = Alarm(**TEST_ALARM)
        self.assertFalse(alarm.match_meter(meter))

    def test_match_meter(self):
        a_id = self.id()
        meter = {
            'counter_name': TEST_ALARM['counter_name'],
            'resource_id': a_id,
        }
        alarm = Alarm(**TEST_ALARM)
        alarm.resource_id = a_id
        self.assertTrue(alarm.match_meter(meter))

    def test_match_meter_without_resource_id(self):
        meter = {'counter_name': TEST_ALARM['counter_name']}
        alarm = Alarm(**TEST_ALARM)
        self.assertTrue(alarm.match_meter(meter))

    def test_alarm_kept_state(self):
        meter = {'counter_name': TEST_ALARM['counter_name']}
        alarm = Alarm(**TEST_ALARM)
        alarm.state = ALARM_OK

        conn = self.mox.CreateMock(storage.base.Connection)
        conn.get_meter_statistics(
            IgnoreArg(),
            period=alarm.period
        ).AndReturn([{'avg': 1.0, 'period': alarm.period,
                      'duration': float(alarm.period) / 60.0}])

        self.mox.ReplayAll()

        alarm.check_state(conn, meter)

        self.assertEqual(alarm.state, ALARM_OK)
        self.assertFalse(os.path.exists('ceilometer_alarm_test_alarm'))
        self.assertFalse(os.path.exists('ceilometer_alarm_test_ok'))
        self.assertFalse(os.path.exists(
            'ceilometer_alarm_test_insufficient_data'))
        self.mox.VerifyAll()

    def test_alarm_change_state_to_alarm(self):
        meter = {'counter_name': TEST_ALARM['counter_name']}
        alarm = Alarm(**TEST_ALARM)

        conn = self.mox.CreateMock(storage.base.Connection)
        conn.get_meter_statistics(
            IgnoreArg(),
            period=alarm.period
        ).AndReturn([{'avg': 2.0, 'period': alarm.period,
                      'duration': float(alarm.period) / 60.0}])

        self.mox.ReplayAll()

        alarm.check_state(conn, meter)

        self.assertEqual(alarm.state, ALARM_ALARM)
        self.assertTrue(os.path.exists('ceilometer_alarm_test_alarm'))
        self.mox.VerifyAll()

    def test_alarm_change_state_to_ok(self):
        meter = {'counter_name': TEST_ALARM['counter_name']}
        alarm = Alarm(**TEST_ALARM)

        conn = self.mox.CreateMock(storage.base.Connection)
        conn.get_meter_statistics(
            IgnoreArg(),
            period=alarm.period
        ).AndReturn([{'avg': 0.0, 'period': alarm.period,
                      'duration': float(alarm.period) / 60.0}])

        self.mox.ReplayAll()

        alarm.check_state(conn, meter)

        self.assertEqual(alarm.state, ALARM_OK)
        self.assertTrue(os.path.exists('ceilometer_alarm_test_ok'))
        self.mox.VerifyAll()

    def test_alarm_change_state_to_insufficient_data(self):
        meter = {'counter_name': TEST_ALARM['counter_name']}
        alarm = Alarm(**TEST_ALARM)
        alarm.state = ALARM_OK

        conn = self.mox.CreateMock(storage.base.Connection)
        conn.get_meter_statistics(
            IgnoreArg(),
            period=alarm.period
        ).AndReturn([{'avg': 0.0, 'period': alarm.period,
                      'duration': 0.0}])

        self.mox.ReplayAll()
        alarm.check_state(conn, meter)

        self.assertEqual(alarm.state, ALARM_INSUFFICIENT_DATA)
        self.assertTrue(os.path.exists(
            'ceilometer_alarm_test_insufficient_data'))
        self.mox.VerifyAll()

    def test_alarm_execute_action_works(self):
        alarm = Alarm(**TEST_ALARM)
        self.assertTrue(alarm._execute('touch ceilometer_alarm_test_ok',
                                       {'sum': 6.0}))

    def test_alarm_execute_action_fails(self):
        alarm = Alarm(**TEST_ALARM)
        self.assertFalse(alarm._execute('invalidcommand', {'sum': 6}))
