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

import eventlet
import requests

import mox

from ceilometer.alarm.alarm import Alarm, ALARM_OK, ALARM_ALARM, \
    ALARM_INSUFFICIENT_DATA
from ceilometer.alarm.aggregated_metric import AggregatedMetric
from ceilometer.exception import InvalidComparisonOperator
from ceilometer.tests import base as tests_base

TEST_ALARM = {
    'id': '1',
    'name': 'SwiftObjectAlarm',
    'counter_name': 'storage.objects',
    'comparison_operator': 'gt',
    'project_id': '',
    'user_id': '',
    'threshold': 2.0,
    'statistic': 'average',
    'evaluation_period': 1,
    'aggregate_period': 60,
    'ok_actions': ['http://localhost:8080/test_ok?state=%(state)s'],
    'alarm_actions': ['http://localhost:8080/test_alarm?state=%(state)s'],
    'insufficient_data_actions':
    ['http://localhost:8080/test_insufficient_data?state=%(state)s']
}


class TestAlarm(tests_base.TestCase):
    def test_create_alarm(self):
        alarm = Alarm(id='1',
                      name='name',
                      counter_name='counter_name',
                      project_id='project_id',
                      user_id='user_id',
                      comparison_operator='eq',
                      threshold=2.0,
                      statistic='sum',
                      evaluation_period=1,
                      aggregate_period=60,
                      ok_actions=['ok_action'],
                      alarm_actions=['alarm_action'],
                      insufficient_data_actions=['insufficient_data_action'],
                      enabled=False,
                      description='desc'
                      )
        self.assertEqual(alarm.id, '1')
        self.assertEqual(alarm.enabled, False)
        self.assertEqual(alarm.name, 'name')
        self.assertEqual(alarm.project_id, 'project_id')
        self.assertEqual(alarm.user_id, 'user_id')
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
                      project_id='project_id',
                      user_id='user_id',
                      comparison_operator='eq',
                      threshold=2.0,
                      statistic='sum',
                      evaluation_period=1,
                      aggregate_period=60
                      )

        self.assertEqual(alarm.id, None)
        self.assertEqual(alarm.enabled, True)
        self.assertEqual(alarm.name, 'name')
        self.assertEqual(alarm.project_id, 'project_id')
        self.assertEqual(alarm.user_id, 'user_id')
        self.assertEqual(alarm.description, '')
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
                          project_id='project_id',
                          user_id='user_id',
                          comparison_operator='invalid_operator',
                          threshold=2.0,
                          statistic='average',
                          evaluation_period=1,
                          aggregate_period=60)

    def test_alarm_kept_state(self):
        aggregates = [AggregatedMetric(TEST_ALARM['id'], average=2.0),
                      AggregatedMetric(TEST_ALARM['id'], average=2.0)]
        alarm = Alarm(**TEST_ALARM)
        alarm.state = ALARM_OK

        self.assertFalse(alarm.check_state(aggregates))
        self.assertEqual(alarm.state, ALARM_OK)

    def test_alarm_change_state_to_alarm(self):
        aggregates = [AggregatedMetric(TEST_ALARM['id'], average=3.0),
                      AggregatedMetric(TEST_ALARM['id'], average=3.0)]
        alarm = Alarm(**TEST_ALARM)

        self.assertTrue(alarm.check_state(aggregates))
        self.assertEqual(alarm.state, ALARM_ALARM)

    def test_alarm_change_state_to_ok(self):
        aggregates = [AggregatedMetric(TEST_ALARM['id'], average=1.0),
                      AggregatedMetric(TEST_ALARM['id'], average=1.0)]
        alarm = Alarm(**TEST_ALARM)

        self.assertTrue(alarm.check_state(aggregates))
        self.assertEqual(alarm.state, ALARM_OK)

    def test_alarm_change_state_to_insufficient_data(self):
        aggregates = []
        alarm = Alarm(**TEST_ALARM)
        alarm.state = ALARM_OK

        self.assertTrue(alarm.check_state(aggregates))
        self.assertEqual(alarm.state, ALARM_INSUFFICIENT_DATA)

    def test_alarm_execute_actions(self):
        alarm = Alarm(**TEST_ALARM)
        alarm.state = ALARM_OK

        self.mox.StubOutWithMock(eventlet, 'spawn_n')

        eventlet.spawn_n(requests.post,
                         'http://localhost:8080/test_ok?state=1',
                         data=mox.ContainsKeyValue("name", TEST_ALARM["name"]))
        self.mox.ReplayAll()
        alarm._do_actions()
        self.mox.VerifyAll()
