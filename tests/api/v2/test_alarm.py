# -*- encoding: utf-8 -*-
#
# Copyright © 2013 eNovance <licensing@enovance.com>
#
# Author: Mehdi Abaakouk <mehdi.abaakouk@enovance.com>
#
# Licensed under the Apache License, Version 2.0 (the 'License'); you may
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
'''Tests alarm operation
'''

import logging

from .base import FunctionalTest

from ceilometer.alarm.alarm import Alarm

LOG = logging.getLogger(__name__)


class TestListEmptyAlarms(FunctionalTest):

    def test_empty(self):
        data = self.get_json('/alarms')
        self.assertEquals([], data)


class TestAlarms(FunctionalTest):

    def setUp(self):
        super(TestAlarms, self).setUp()

        for alarm in [Alarm(name='name1', counter_name='meter.test',
                            comparison_operator='gt', threshold=2.0,
                            statistic='average',
                            user_id='XXX', project_id='XXX'),
                      Alarm(name='name2', counter_name='meter.mine',
                            comparison_operator='gt', threshold=2.0,
                            statistic='average',
                            user_id='XXX', project_id='XXX'),
                      Alarm(name='name3', counter_name='meter.test',
                            comparison_operator='gt', threshold=2.0,
                            statistic='average',
                            user_id='XXX', project_id='XXX')
                      ]:
            self.alarm_conn.alarm_add(alarm)

    def test_list_alarms(self):
        data = self.get_json('/alarms')
        self.assertEquals(3, len(data))
        self.assertEquals(set(r['name'] for r in data),
                          set(['name1',
                               'name2',
                               'name3']))
        self.assertEquals(set(r['counter_name'] for r in data),
                          set(['meter.test',
                               'meter.mine']))

    def _test_get_alarm(self):
        #FIXME:(sileht) won't work  but I don't understand why ...
        data = self.get_json('/alarms/1')
        self.assertEquals(data['name'], 'name1')
        self.assertEquals(data['counter_name'], 'meter.test')

    def _test_post_invalid_alarm(self):
        #TODO(sileht):
        pass

    def test_post_alarm(self):
        json = {
            'name': 'added_alarm',
            'counter_name': 'ameter',
            'comparison_operator': 'gt',
            'threshold': 2.0,
            'statistic': 'average',
        }
        self.post_json('/alarms', params=json, status=200)
        alarms = list(self.alarm_conn.alarm_list())
        self.assertEquals(4, len(alarms))

    def test_put_alarm(self):
        json = {
            'name': 'renameded_alarm',
        }
        self.put_json('/alarms/1', params=json, status=200)
        alarm = self.alarm_conn.alarm_get(1)
        self.assertEquals(alarm.name, json['name'])

    def test_delete_alarm(self):
        self.delete('/alarms/1', status=200)
        alarms = list(self.alarm_conn.alarm_list())
        self.assertEquals(2, len(alarms))
