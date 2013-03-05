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

import datetime
import os

from ceilometer.alarm.alarm import Alarm, ALARM_OK, ALARM_ALARM, \
    ALARM_INSUFFICIENT_DATA
from ceilometer.exception import InvalidComparisonOperator
from ceilometer.exception import AlarmParameterUnknown
from ceilometer.openstack.common import timeutils
from ceilometer.tests import base as tests_base

TEST_ALARM = {
    'id': '1',
    'name': 'SwiftObjectAlarm',
    'counter_name': 'storage.objects',
    'comparison_operator': 'gt',
    'threshold': 2.0,
    'statistic': 'average',
    'evaluation_period': 1,
    'aggregate_period': 60,
    'ok_actions': ['touch ceilometer_alarm_test_ok'],
    'alarm_actions': ['touch ceilometer_alarm_test_alarm'],
    'insufficient_data_actions':
    ['touch ceilometer_alarm_test_insufficient_data']
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
        alarm = Alarm(id='1',
                      name='name',
                      counter_name='counter_name',
                      comparison_operator='eq',
                      threshold=2.0,
                      statistic='sum',
                      evaluation_period=1,
                      aggregate_period=60,
                      ok_actions=['ok_action'],
                      alarm_actions=['alarm_action'],
                      insufficient_data_actions=['insufficient_data_action'],
                      enabled=False,
                      description="desc"
                      )
        self.assertEqual(alarm.id, '1')
        self.assertEqual(alarm.enabled, False)
        self.assertEqual(alarm.name, 'name')
        self.assertEqual(alarm.description, 'desc')
        self.assertEqual(alarm.counter_name, 'counter_name')
        self.assertEqual(alarm.comparison_operator, 'eq')
        self.assertEqual(alarm.threshold, 2.0)
        self.assertEqual(alarm.statistic, 'sum')
        self.assertEqual(alarm.aggregate_period, 60)
        self.assertEqual(alarm.evaluation_period, 1)
        self.assertEqual(alarm.ok_actions, ['ok_action'])
        self.assertEqual(alarm.alarm_actions, ['alarm_action'])
        self.assertEqual(alarm.insufficient_data_actions,
                         ['insufficient_data_action'])

    def test_create_alarm_with_default(self):
        alarm = Alarm(name='name',
                      counter_name='counter_name',
                      comparison_operator='eq',
                      threshold=2.0,
                      statistic='sum',
                      evaluation_period=1,
                      aggregate_period=60
                      )

        self.assertEqual(alarm.id, None)
        self.assertEqual(alarm.enabled, True)
        self.assertEqual(alarm.name, 'name')
        self.assertEqual(alarm.description, None)
        self.assertEqual(alarm.counter_name, 'counter_name')
        self.assertEqual(alarm.comparison_operator, 'eq')
        self.assertEqual(alarm.threshold, 2.0)
        self.assertEqual(alarm.statistic, 'sum')
        self.assertEqual(alarm.aggregate_period, 60)
        self.assertEqual(alarm.evaluation_period, 1)
        self.assertEqual(alarm.ok_actions, [])
        self.assertEqual(alarm.alarm_actions, [])
        self.assertEqual(alarm.insufficient_data_actions, [])

    def test_create_invalid_alarm(self):
        self.assertRaises(InvalidComparisonOperator, Alarm,
                          name='name',
                          counter_name='counter_name',
                          comparison_operator='invalid_operator',
                          threshold=2.0,
                          statistic='average',
                          evaluation_period=1,
                          aggregate_period=60)

        self.assertRaises(AlarmParameterUnknown, Alarm,
                          name='name',
                          counter_name='counter_name',
                          comparison_operator='ge',
                          threshold=2.0,
                          statistic='average',
                          evaluation_period=1,
                          aggregate_period=60,
                          invalid_parameter="invalid")

    def test_alarm_kept_state(self):
        aggregates = [{'average': 2.0}, {'average': 2.0}]

        alarm = Alarm(**TEST_ALARM)
        alarm.state = ALARM_OK
        alarm.check_state(aggregates)

        self.assertEqual(alarm.state, ALARM_OK)
        self.assertFalse(os.path.exists('ceilometer_alarm_test_alarm'))
        self.assertFalse(os.path.exists('ceilometer_alarm_test_ok'))
        self.assertFalse(os.path.exists(
            'ceilometer_alarm_test_insufficient_data'))

    def test_alarm_change_state_to_alarm(self):
        aggregates = [{'average': 3.0}, {'average': 3.0}]

        alarm = Alarm(**TEST_ALARM)
        alarm.check_state(aggregates)

        self.assertEqual(alarm.state, ALARM_ALARM)
        self.assertTrue(os.path.exists('ceilometer_alarm_test_alarm'))

    def test_alarm_change_state_to_ok(self):
        aggregates = [{'average': 1.0}, {'average': 1.0}]
        alarm = Alarm(**TEST_ALARM)

        alarm.check_state(aggregates)

        self.assertEqual(alarm.state, ALARM_OK)
        self.assertTrue(os.path.exists('ceilometer_alarm_test_ok'))

    def test_alarm_change_state_to_insufficient_data(self):
        aggregates = []
        alarm = Alarm(**TEST_ALARM)
        alarm.state = ALARM_OK

        alarm.check_state(aggregates)

        self.assertEqual(alarm.state, ALARM_INSUFFICIENT_DATA)
        self.assertTrue(os.path.exists(
            'ceilometer_alarm_test_insufficient_data'))

    def test_alarm_execute_action_works(self):
        alarm = Alarm(**TEST_ALARM)
        self.assertTrue(alarm._execute('touch ceilometer_alarm_test_ok'))

    def test_alarm_execute_action_fails(self):
        alarm = Alarm(**TEST_ALARM)
        self.assertFalse(alarm._execute('invalidcommand'))

    def test_aggregated_metric_update(self):
        meter = {'counter_name': 'storage.objects', 'counter_volume': 6.0}
        aggregates = [{'average': 3.0, 'sum': 6.0, 'maximum': 4.0,
                       'minimum': 2.0, 'sample_count': 2,
                       'timestamp': timeutils.utcnow()}]
        alarm = Alarm(**TEST_ALARM)
        alarm.update_aggregated_metric_data(meter, aggregates)
        assert aggregates[0]['sum'] == 12.0
        assert aggregates[0]['maximum'] == 6.0
        assert aggregates[0]['minimum'] == 2.0
        assert aggregates[0]['sample_count'] == 3.0
        assert aggregates[0]['average'] == 4.0

    def test_aggregated_metric_update_minimum(self):
        meter = {'counter_name': 'storage.objects', 'counter_volume': 0.0}
        aggregates = [{'average': 3.0, 'sum': 6.0, 'maximum': 4.0,
                       'minimum': 2.0, 'sample_count': 2,
                       'timestamp': timeutils.utcnow()}]
        alarm = Alarm(**TEST_ALARM)
        alarm.update_aggregated_metric_data(meter, aggregates)
        assert aggregates[0]['sum'] == 6.0
        assert aggregates[0]['maximum'] == 4.0
        assert aggregates[0]['minimum'] == 0.0
        assert aggregates[0]['sample_count'] == 3.0
        assert aggregates[0]['average'] == 2.0

    def test_aggregated_metric_update_new_aggregates(self):
        meter = {'counter_name': 'storage.objects', 'counter_volume': 2.0}
        aggregates = []
        alarm = Alarm(**TEST_ALARM)
        alarm.update_aggregated_metric_data(meter, aggregates)
        assert len(aggregates) == 1
        assert aggregates[0]['sum'] == 2.0
        assert aggregates[0]['maximum'] == 2.0
        assert aggregates[0]['minimum'] == 2.0
        assert aggregates[0]['sample_count'] == 1.0
        assert aggregates[0]['average'] == 2.0

    def test_aggregated_metric_update_previous_aggregates_expired(self):
        meter = {'counter_name': 'storage.objects', 'counter_volume': 2.0}
        aggregates = [{'average': 3.0, 'sum': 6.0, 'maximum': 4.0,
                       'minimum': 2.0, 'sample_count': 2,
                       'timestamp': timeutils.utcnow() -
                       datetime.timedelta(seconds=1000000)}]

        alarm = Alarm(**TEST_ALARM)
        alarm.update_aggregated_metric_data(meter, aggregates)
        print aggregates
        assert len(aggregates) == 2
        assert aggregates[0]['sum'] == 2.0
        assert aggregates[0]['maximum'] == 2.0
        assert aggregates[0]['minimum'] == 2.0
        assert aggregates[0]['sample_count'] == 1.0
        assert aggregates[0]['average'] == 2.0
