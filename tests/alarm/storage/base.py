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

from ceilometer.alarm.alarm import Alarm, ALARM_ALARM
from ceilometer.tests import base as test_base
from ceilometer.openstack.common import timeutils


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
        self.alarm1 = Alarm(name='alarmtest', counter_name='storage.objects',
                            comparison_operator='ge',
                            threshold=2.0, statistic='average',
                            evaluation_period=1,
                            aggregate_period=60,
                            enabled=False)
        self.alarm2 = Alarm(name='alarmtest', counter_name='storage.objects',
                            comparison_operator='ge',
                            threshold=2.0, statistic='average',
                            evaluation_period=1,
                            aggregate_period=60,
                            alarm_metadatas=[('user_id', '1234567890')])
        self.alarm3 = Alarm(name='alarmtest', counter_name='storage.objects',
                            comparison_operator='ge',
                            threshold=2.0, statistic='average',
                            evaluation_period=1,
                            aggregate_period=60,
                            user_id='0987654321',
                            project_id='0987654321'
                            )
        self.alarm1 = Alarm(**self.conn.alarm_add(self.alarm1.items()))
        self.alarm2 = Alarm(**self.conn.alarm_add(self.alarm2.items()))
        self.alarm3 = Alarm(**self.conn.alarm_add(self.alarm3.items()))

        self.agg1 = self.conn.aggregated_metric_update(None, {
            'alarm_id': 2,
            'average': 2.0, 'sum': 2.0, 'maximum': 2.0,
            'minimum': 2.0, 'sample_count': 1,
            'timestamp': timeutils.utcnow() -
            datetime.timedelta(seconds=360)
        })

        self.agg2 = self.conn.aggregated_metric_update(None, {
            'alarm_id': 2,
            'average': 3.0, 'sum': 6.0, 'maximum': 4.0,
            'minimum': 2.0, 'sample_count': 2,
            'timestamp': timeutils.utcnow() -
            datetime.timedelta(seconds=240)
        })

        self.agg3 = self.conn.aggregated_metric_update(None, {
            'alarm_id': 2,
            'average': 4.0, 'sum': 12.0, 'maximum': 12.0,
            'minimum': 2.0, 'sample_count': 3,
            'timestamp': timeutils.utcnow() -
            datetime.timedelta(seconds=120)
        })
        print ">>>>>>>", self.agg1


class AlarmTest(DBTestBase):
    def test_alarm_get_by_id(self):
        obj = self.conn.alarm_get(self.alarm2.id)
        self.assertEqual(self.alarm2.name, obj['name'])
        self.assertEqual(self.alarm2.id, obj['id'])

    def test_alarm_list(self):
        """test only enabled alarm
        """
        objs = list(self.conn.alarm_list())
        self.assertEqual(len(objs), 2)

    def test_alarm_list_with_owner(self):
        objs = list(self.conn.alarm_list(user_id='0987654321'))
        self.assertEqual(len(objs), 1)
        self.assertEqual(self.alarm3.id, objs[0]['id'])

    def test_alarm_list_with_metadata(self):
        objs = list(self.conn.alarm_list(
            metaquery=[('user_id', '1234567890')]))

        self.assertEqual(len(objs), 2)
        self.assertEqual(self.alarm2.id, objs[0]['id'])
        self.assertEqual(self.alarm3.id, objs[1]['id'])

    def test_alarm_list_by_counter_name(self):
        objs = list(self.conn.alarm_list(counter_name='storage.objects',
                                         enabled=None))
        self.assertEqual(len(objs), 3)

    def test_alarm_list_by_name(self):
        objs = list(self.conn.alarm_list('alarmtest', enabled=None))
        self.assertEqual(len(objs), 3)

    def test_alarm_list_by_name_with_owner(self):
        objs = list(self.conn.alarm_list(name='alarmtest',
                                         user_id='0987654321',
                                         project_id='0987654321'))
        self.assertEqual(len(objs), 1)
        self.assertEqual(self.alarm3.id, objs[0]['id'])

    def test_alarm_list_by_counter_name_with_metadata(self):
        objs = list(self.conn.alarm_list(
            counter_name='storage.objects',
            metaquery=[('user_id', '1234567890')])
        )
        self.assertEqual(len(objs), 2)
        self.assertEqual(self.alarm2.id, objs[0]['id'])
        self.assertEqual(self.alarm3.id, objs[1]['id'])

    def test_alarm_update_state(self):
        obj = self.conn.alarm_update_state(self.alarm1.id, ALARM_ALARM,
                                           timeutils.utcnow())
        self.assertEqual(obj['state'], ALARM_ALARM)
        self.assertNotEqual(obj['state_timestamp'],
                            self.alarm1.state_timestamp)

    def test_aggregated_metric_get(self):
        obj = self.conn.aggregated_metric_get(self.agg1['id'])
        self.assertEqual(obj['id'], self.agg1['id'])

    def test_aggregated_metric_list(self):
        objs = list(self.conn.aggregated_metric_list(self.alarm2.id))
        self.assertEqual(len(objs), 3)

    def test_aggregated_metric_list_limit(self):
        objs = list(self.conn.aggregated_metric_list(self.alarm2.id, limit=1))
        self.assertEqual(len(objs), 1)

    def test_aggregated_metric_list_start(self):
        objs = list(self.conn.aggregated_metric_list(self.alarm2.id,
                    start=timeutils.utcnow() -
                    datetime.timedelta(seconds=260)))
        self.assertEqual(len(objs), 2)

    def test_aggregated_metric_add(self):
        self.conn.aggregated_metric_update(None, {
            'alarm_id': 2,
            'average': 4.0, 'sum': 12.0, 'maximum': 12.0,
            'minimum': 2.0, 'sample_count': 200.0,
            'timestamp': timeutils.utcnow() -
            datetime.timedelta(seconds=1)
        })
        # new element must be the first one
        objs = list(self.conn.aggregated_metric_list(self.alarm2.id, limit=1))

        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0]['sample_count'], 200.0)

    def test_aggregated_metric_update(self):
        data = self.conn.aggregated_metric_get(self.agg3['id'])
        data['sum'] = 10000.0
        self.conn.aggregated_metric_update(self.agg3['id'], data)
        data = self.conn.aggregated_metric_get(self.agg3['id'])
        self.assertEqual(data['sum'], 10000.0)

    def test_alarm_delete(self):
        """test delete alarm
        """
        self.conn.alarm_delete(self.alarm2.id)
        objs = list(self.conn.alarm_list(enabled=False))
        self.assertEqual(len(objs), 2)
        objs = list(self.conn.aggregated_metric_list(self.alarm2.id))
        self.assertEqual(len(objs), 0)
