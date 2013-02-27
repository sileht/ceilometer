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
""" Base classes for DB backend implemtation test
"""

import abc
import datetime

from ceilometer import exception
from ceilometer.alarm.alarm import ALARM_ALARM
from ceilometer.alarm.alarm import Alarm as AlarmModel
from ceilometer.alarm.aggregated_metric import AggregatedMetric as \
    AggregatedMetricModel
from ceilometer.tests import base as test_base
from ceilometer.openstack.common import timeutils

from ceilometer.alarm.storage.sqlalchemy.models import Alarm
from ceilometer.alarm.storage.sqlalchemy.models import AggregatedMetric


ALARM_FIXTURE = [
    {'name': 'alarmtest',
     'counter_name': 'storage.objects',
     'comparison_operator': 'ge',
     'threshold': 2.0,
     'statistic': 'average',
     'evaluation_period': 3,
     'aggregate_period': 60,
     'matching_metadata': {},
     'enabled': False,
     'state_timestamp': timeutils.utcnow(),
     'user_id': None,
     'project_id': None},
    {'name': 'alarmtest',
     'counter_name': 'storage.objects',
     'comparison_operator': 'ge',
     'threshold': 2.0,
     'statistic': 'average',
     'evaluation_period': 3,
     'aggregate_period': 60,
     'matching_metadata': {'user_id': '1234567890'},
     'enabled': True,
     'state_timestamp': timeutils.utcnow(),
     'user_id': None,
     'project_id': None},
    {'name': 'alarmtest',
     'counter_name': 'storage.objects',
     'comparison_operator': 'ge',
     'threshold': 2.0,
     'statistic': 'average',
     'evaluation_period': 3,
     'aggregate_period': 60,
     'matching_metadata': {},
     'enabled': True,
     'state_timestamp': timeutils.utcnow(),
     'user_id': '0987654321',
     'project_id': '0987654321'}
]
ALARM_FIXTURE_SUP = {
    'name': 'alarmtest_sup',
    'counter_name': 'storage.objects',
    'comparison_operator': 'ge',
    'threshold': 2.0,
    'statistic': 'average',
    'evaluation_period': 3,
    'aggregate_period': 60,
    'matching_metadata': {},
    'enabled': True,
    'state_timestamp': timeutils.utcnow(),
    'user_id': None,
    'project_id': None
}

AGGREGATED_METRIC_FIXTURE = [
    {'alarm_id': '2',
     'average': 2.0, 'sum': 2.0, 'maximum': 2.0,
     'minimum': 2.0, 'sample_count': 1,
     'timestamp': timeutils.utcnow() -
     datetime.timedelta(seconds=360)},
    {'alarm_id': '2',
     'average': 3.0, 'sum': 6.0, 'maximum': 4.0,
     'minimum': 2.0, 'sample_count': 2,
     'timestamp': timeutils.utcnow() -
     datetime.timedelta(seconds=240)},
    {'alarm_id': '2',
     'average': 4.0, 'sum': 12.0, 'maximum': 12.0,
     'minimum': 2.0, 'sample_count': 3,
     'timestamp': timeutils.utcnow() -
     datetime.timedelta(seconds=120)},
]
AGGREGATED_METRIC_FIXTURE_SUP = {
    'alarm_id': '2',
    'average': 0.0, 'sum': 0.0, 'maximum': 0.0,
    'minimum': 0.0, 'sample_count': 1,
    'timestamp': timeutils.utcnow()
}


class DBEngineBase(object):
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def get_connection(self):
        """Return an open connection to the DB
        """

    @abc.abstractmethod
    def clean_up(self):
        """Clean up all resources allocated in get_connection()
        """


class DBTestBase(test_base.TestCase):
    __metaclass__ = abc.ABCMeta

    @classmethod
    @abc.abstractmethod
    def get_engine(cls):
        '''Return an instance of the class which implements
           the DBEngineTestBase abstract class
        '''

    def tearDown(self):
        self.engine.clean_up()
        self.conn = None
        self.engine = None
        super(DBTestBase, self).tearDown()

    def setUp(self):
        super(DBTestBase, self).setUp()
        self.engine = self.get_engine()
        self.conn = self.engine.get_connection()
        self.prepare_data()

    def prepare_data(self):
        for alarm in ALARM_FIXTURE:
            a = Alarm(**alarm)
            self.conn.session.add(a)
            self.conn.session.flush()
            alarm['id'] = a.id

        for agg in AGGREGATED_METRIC_FIXTURE:
            agg['alarm_id'] = ALARM_FIXTURE[1]['id']
            a = AggregatedMetric(**agg)
            self.conn.session.add(a)
            self.conn.session.flush()
            agg['id'] = a.id


class AlarmTest(DBTestBase):
    def test_alarm_add(self):
        obj = self.conn.alarm_add(
            AlarmModel(**ALARM_FIXTURE_SUP))

        for k in ALARM_FIXTURE_SUP.keys():
            self.assertEqual(getattr(obj, k), ALARM_FIXTURE_SUP[k])

        objs = list(self.conn.alarm_list(enabled=None))
        self.assertEqual(len(objs), 4)

        obj = self.conn.alarm_get(obj.id)
        for k in ALARM_FIXTURE_SUP.keys():
            self.assertEqual(getattr(obj, k), ALARM_FIXTURE_SUP[k])

    def test_alarm_get_by_id(self):
        obj = self.conn.alarm_get(ALARM_FIXTURE[1]['id'])
        self.assertEqual(ALARM_FIXTURE[1]['name'], obj.name)
        self.assertEqual(ALARM_FIXTURE[1]['id'], obj.id)

    def test_alarm_list_enabled(self):
        """test only enabled alarm
        """
        ids = list(self.conn.alarm_list(enabled=True))
        self.assertEqual(len(ids), 2)

    def test_alarm_list_with_owner(self):
        ids = list(self.conn.alarm_list(user_id='0987654321'))
        self.assertEqual(len(ids), 1)

        obj = self.conn.alarm_get(ids[0])
        self.assertEqual(ALARM_FIXTURE[2]['id'], obj.id)

    def test_alarm_list_by_name(self):
        objs = list(self.conn.alarm_list('alarmtest', enabled=None))
        self.assertEqual(len(objs), 3)

    def test_alarm_list_by_name_with_owner(self):
        ids = list(self.conn.alarm_list(name='alarmtest',
                                        user_id='0987654321',
                                        project_id='0987654321'))
        obj = self.conn.alarm_get(ids[0])
        self.assertEqual(len(ids), 1)
        self.assertEqual(ALARM_FIXTURE[2]['id'], obj.id)

    def test_alarm_update(self):
        obj = self.conn.alarm_get(ALARM_FIXTURE[1]['id'])
        obj.state = ALARM_ALARM
        obj.state_timestamp = timeutils.utcnow()
        self.conn.alarm_update(obj)

        updated_obj = self.conn.alarm_get(ALARM_FIXTURE[1]['id'])
        for k in ['state', 'state_timestamp']:
            self.assertEqual(getattr(obj, k), getattr(updated_obj, k))

    def test_alarm_delete(self):
        self.conn.alarm_delete(ALARM_FIXTURE[1]['id'])
        objs = list(self.conn.alarm_list())
        self.assertEqual(len(objs), 2)
        objs = list(self.conn.aggregated_metric_list(ALARM_FIXTURE[1]['id']))
        self.assertEqual(len(objs), 0)

    def test_aggregated_metric_add(self):
        obj = self.conn.aggregated_metric_add(
            AggregatedMetricModel(**AGGREGATED_METRIC_FIXTURE_SUP))

        for k in AGGREGATED_METRIC_FIXTURE_SUP.keys():
            self.assertEqual(getattr(obj, k), AGGREGATED_METRIC_FIXTURE_SUP[k])

        objs = list(self.conn.aggregated_metric_list(ALARM_FIXTURE[1]['id']))
        self.assertEqual(len(objs), 4)

        obj = self.conn.aggregated_metric_get(obj.id)
        for k in AGGREGATED_METRIC_FIXTURE_SUP.keys():
            self.assertEqual(getattr(obj, k), AGGREGATED_METRIC_FIXTURE_SUP[k])

    def test_aggregated_metric_update(self):
        obj = self.conn.aggregated_metric_get(
            AGGREGATED_METRIC_FIXTURE[1]['id'])
        obj.sample_count = 15
        self.conn.aggregated_metric_update(obj)

        updated_obj = self.conn.aggregated_metric_get(
            AGGREGATED_METRIC_FIXTURE[1]['id'])
        self.assertEqual(obj.sample_count, updated_obj.sample_count)

    def test_aggregated_metric_get(self):
        obj = self.conn.aggregated_metric_get(
            AGGREGATED_METRIC_FIXTURE[1]['id'])
        self.assertEqual(obj.id, AGGREGATED_METRIC_FIXTURE[1]['id'])

    def test_aggregated_metric_list(self):
        objs = list(self.conn.aggregated_metric_list(ALARM_FIXTURE[1]['id']))
        self.assertEqual(len(objs), 3)

    def test_aggregated_metric_delete(self):
        self.conn.aggregated_metric_delete(AGGREGATED_METRIC_FIXTURE[1]['id'])
        self.assertRaises(exception.AggregateNotFound,
                          self.conn.aggregated_metric_get,
                          AGGREGATED_METRIC_FIXTURE[1]['id'])
